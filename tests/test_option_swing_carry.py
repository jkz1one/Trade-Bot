"""Carry evidence never changes the native session-close execution policy."""

import asyncio
import copy
import json
import stat
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError
from test_degen_options import AT, policies
from test_option_execution import configuration, intent_for
from test_option_shared_strategy import owner, shared_frame, swing_input, swing_policy

from app.options.engine import fingerprint
from app.options.swing import SwingTerminal
from app.options.swing_carry import (
    MAX_BYTES,
    SwingCarryPolicy,
    SwingCarryRequest,
    export_swing_carry,
    review_swing_carry,
    verify_swing_carry_export,
)
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def request(right="CALL", target=date(2026, 10, 9), exit_session=None):
    cal = XNYSCalendar().calendar
    exit_session = exit_session or cal.next_session(target.isoformat()).date()
    at = cal.session_open(target.isoformat()).to_pydatetime() + timedelta(minutes=30)
    item = swing_input(right, target)
    item = item.model_copy(
        update={
            "seed": item.seed.model_copy(
                update={"first_target": D(605 if right == "CALL" else 595)}
            ),
            "catalyst": item.catalyst.model_copy(
                update={
                    "valid_through": cal.session_close(exit_session.isoformat()).to_pydatetime(),
                }
            ),
        }
    )
    f = shared_frame(right, item)
    delta = at - AT
    history = f.histories[0].model_copy(
        update={
            "source_at": at,
            "received_at": at,
            "bars": tuple(
                b.model_copy(update={"begins_at": b.begins_at + delta}) for b in f.histories[0].bars
            ),
        }
    )
    _data, limits, execution = configuration(right)
    structure, selection = policies()
    from app.options.models import OptionAccount

    account = OptionAccount(
        account_id=limits.account_id,
        population_id=limits.population_id,
        snapshot_id="carry-fixture",
        captured_at=at,
        complete=True,
        reconciled=True,
        cash="1000",
        settled_cash="1000",
        reserved_cash="0",
        daily_loss_available="600",
        total_loss_available="800",
        budgets_known=True,
        position=None,
        working_orders=0,
        unsupported_exposure=False,
        entry_halted=False,
    )
    return SwingCarryRequest(
        at=at,
        exit_session=exit_session,
        carry=SwingCarryPolicy(
            maximum_carry_sessions=3,
            maximum_calendar_days=10,
            exit_before_close_minutes=20,
            expiry_session_buffer=1,
        ),
        swing=swing_policy(unfilled_lifecycle="observed-lifecycle-v3"),
        structure=structure,
        selection=selection,
        execution=execution,
        limits=limits,
        item=item,
        history=history,
        account=account,
        quote=f.quotes[1].model_copy(update={"source_at": at, "received_at": at}),
        underlying=f.underlyings[0].model_copy(update={"source_at": at, "received_at": at}),
    )


def changed(r, field, **kwargs):
    return r.model_copy(update={field: getattr(r, field).model_copy(update=kwargs)})


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_ready_calendar_evidence_keeps_day_admission_and_every_fee(right):
    r = request(right)
    out = review_swing_carry(r)
    assert out.evidence_status == "READY", out.reasons
    assert not out.authority and out.execution_blockers == (
        "SWING_OVERNIGHT_EXECUTION_NOT_ENROLLED",
    )
    assert [s.session for s in out.sessions] == [date(2026, 10, 9), date(2026, 10, 12)]
    assert out.proposed_exit_at == out.sessions[-1].closes_at - timedelta(minutes=20)
    a = out.admission
    assert a.outcome == "APPROVED" and a.quantity > 0
    assert a.valid_until <= out.sessions[0].closes_at
    assert a.reserved_exit_fees == a.quantity * (
        r.limits.exit_fee_per_contract + r.limits.exit_fee_per_order
    )
    assert a.full_premium_loss == a.entry_debit + a.reserved_exit_fees
    assert out.request_hash == fingerprint(r)
    with localcontext() as ctx:
        ctx.prec = 6
        assert review_swing_carry(r) == out


@pytest.mark.parametrize(
    "target,exit_session,open_hour,close_hour",
    [
        (date(2026, 3, 6), date(2026, 3, 9), 13, 20),
        (date(2026, 10, 30), date(2026, 11, 2), 14, 21),
        (date(2026, 7, 2), date(2026, 7, 6), 13, 20),
        (date(2026, 11, 25), date(2026, 11, 27), 14, 18),
    ],
)
def test_actual_holidays_dst_and_half_days(target, exit_session, open_hour, close_hour):
    r = request(target=target, exit_session=exit_session)
    out = review_swing_carry(r)
    assert out.evidence_status == "READY", out.reasons
    assert len(out.sessions) == 2
    assert out.sessions[-1].opens_at.hour == open_hour
    assert out.sessions[-1].closes_at.hour == close_hour
    assert out.proposed_exit_at.minute == 40


@pytest.mark.parametrize(
    "exit_session,reason",
    [
        (date(2026, 10, 9), "SWING_CARRY_CALENDAR_SPAN"),
        (date(2026, 10, 8), "SWING_CARRY_CALENDAR_SPAN"),
        (date(2026, 10, 10), "SWING_CARRY_EXACT_SESSIONS_REQUIRED"),
        (date(2026, 10, 22), "SWING_CARRY_CALENDAR_SPAN"),
        (date(2026, 10, 15), "SWING_CARRY_SESSION_LIMIT"),
    ],
)
def test_no_date_rolling_or_horizon_extension(exit_session, reason):
    out = review_swing_carry(request().model_copy(update={"exit_session": exit_session}))
    assert reason in out.reasons and out.evidence_status == "BLOCKED"
    assert out.sessions == () and out.proposed_exit_at is None


@pytest.mark.parametrize(
    "field,changes,reason",
    [
        ("account", {"budgets_known": False}, "UNKNOWN_COST_OR_LOSS_BUDGET"),
        ("account", {"account_id": "other"}, "ACCOUNT_POPULATION_MISMATCH"),
        ("account", {"population_id": "other"}, "ACCOUNT_POPULATION_MISMATCH"),
        ("account", {"working_orders": 1}, "UNRESOLVED_ORDER"),
        ("account", {"unsupported_exposure": True}, "UNSUPPORTED_ACCOUNT_EXPOSURE"),
        ("account", {"entry_halted": True}, "ENTRY_HALTED"),
        ("account", {"captured_at": AT - timedelta(seconds=60)}, "STALE_OR_FUTURE_ACCOUNT"),
        ("limits", {"session_source": "guessed-calendar"}, "SWING_CARRY_OWNER_POLICY_BINDING"),
        ("underlying", {"bid": D(620), "ask": D(621)}, "SWING_CURRENT_BREAK_OR_CHASE_REJECTED"),
        ("quote", {"source_at": AT + timedelta(seconds=1)}, "INVALID_OPTION_QUOTE_TIME"),
        ("quote", {"complete": False}, "OPTION_COVERAGE_OR_ENTITLEMENT"),
    ],
)
def test_existing_account_and_market_gates_apply(field, changes, reason):
    out = review_swing_carry(changed(request(), field, **changes))
    assert out.evidence_status == "BLOCKED" and reason in out.reasons


@pytest.mark.parametrize(
    "field,changes,reason",
    [
        ("catalyst", {"valid_through": AT.replace(hour=20)}, "SWING_CARRY_CATALYST_HORIZON"),
        ("catalyst", {"status": "UNKNOWN"}, "SWING_CATALYST_CLEARANCE_REQUIRED"),
        (
            "catalyst",
            {"source_at": AT - timedelta(seconds=30)},
            "SWING_CATALYST_CLEARANCE_REQUIRED",
        ),
        ("catalyst", {"source": "other"}, "SWING_CATALYST_CLEARANCE_REQUIRED"),
        ("catalyst", {"symbol": "QQQ"}, "SWING_CATALYST_CLEARANCE_REQUIRED"),
        ("metadata", {"greek_provenance": "ESTIMATED"}, "OBSERVED_DELTA_REQUIRED"),
        ("seed", {"first_target": None}, "SWING_ORIGINAL_FIRST_TARGET_REQUIRED"),
    ],
)
def test_no_clearance_greeks_or_original_objective_inference(field, changes, reason):
    r = request()
    item = r.item.model_copy(update={field: getattr(r.item, field).model_copy(update=changes)})
    out = review_swing_carry(r.model_copy(update={"item": item}))
    assert out.evidence_status == "BLOCKED" and reason in out.reasons


def test_expiry_buffer_and_earlier_contract_instant_are_independent():
    r = changed(request(), "carry", expiry_session_buffer=5)
    assert "SWING_CARRY_EXPIRY_BUFFER" in review_swing_carry(r).reasons
    r = request()
    end = review_swing_carry(r).proposed_exit_at
    contract = r.item.seed.instrument.contract.model_copy(update={"last_trading_at": end})
    instrument = r.item.seed.instrument.model_copy(update={"contract": contract})
    r = changed(
        r,
        "item",
        seed=r.item.seed.model_copy(update={"instrument": instrument}),
        metadata=r.item.metadata.model_copy(update={"instrument": instrument}),
    )
    r = changed(r, "quote", instrument=instrument)
    assert "SWING_CARRY_CONTRACT_CUTOFF" in review_swing_carry(r).reasons


@pytest.mark.parametrize("kind", ["retained", "wrong_seed", "future", "quote", "completed"])
def test_terminal_inputs_never_become_ready(kind):
    r = request()
    if kind in {"retained", "wrong_seed", "future"}:
        terminal = SwingTerminal(
            seed_hash="0" * 64 if kind == "wrong_seed" else fingerprint(r.item.seed),
            status="TARGET_CONSUMED",
            observed_at=r.at + timedelta(seconds=int(kind == "future")),
            triggered_at=r.at,
            first_target=D(605),
            quote=r.underlying,
        )
        r = r.model_copy(update={"retained_terminal": terminal})
    elif kind == "quote":
        r = changed(r, "underlying", bid=D(605), ask=D("605.01"))
    else:
        bars = r.history.bars
        r = changed(r, "history", bars=(*bars[:-1], bars[-1].model_copy(update={"high": D(606)})))
    out = review_swing_carry(r)
    assert out.evidence_status == "BLOCKED"
    assert any("TERMINAL" in x or "TARGET_CONSUMED" in x for x in out.reasons)


@pytest.mark.parametrize("missing", ["quote", "underlying"])
def test_missing_observations_stay_blocked(missing):
    out = review_swing_carry(request().model_copy(update={missing: None}))
    assert out.evidence_status == "BLOCKED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_carry_sessions", 0),
        ("maximum_carry_sessions", True),
        ("maximum_calendar_days", 61),
        ("expiry_session_buffer", 0),
        ("exit_before_close_minutes", 0),
        ("exit_before_close_minutes", 1.5),
    ],
)
def test_explicit_bounded_policy(field, value):
    with pytest.raises(ValidationError):
        review_swing_carry(changed(request(), "carry", **{field: value}))


@pytest.mark.parametrize(
    "change", ["request", "date", "cash", "authority", "status", "version", "extra"]
)
def test_portable_verification_recomputes_every_field(change):
    r = request()
    exported = export_swing_carry(r)
    assert (
        verify_swing_carry_export(exported, expected_request_hash=fingerprint(r))
        == exported["review"]
    )
    bad = copy.deepcopy(exported)
    if change == "request":
        bad["request"]["account"]["population_id"] = "other"
    elif change == "date":
        bad["review"]["proposed_exit_at"] = r.at.isoformat()
    elif change == "cash":
        bad["review"]["admission"]["reserved_exit_fees"] = "0"
    elif change == "authority":
        bad["review"]["authority"] = True
    elif change == "status":
        bad["review"]["evidence_status"] = "APPROVED"
    elif change == "version":
        bad["version"] = "future"
    else:
        bad["credentials"] = "unexpected"
    with pytest.raises(ValueError):
        verify_swing_carry_export(bad, expected_request_hash=fingerprint(r))


def test_ready_preflight_cannot_enable_overnight_or_mutate_owner(tmp_path):
    r = request()
    with owner(tmp_path) as (c, venue, _):
        before = c.engine.journal.report(now=AT)
        assert review_swing_carry(r).evidence_status == "READY"
        assert c.engine.journal.report(now=AT) == before and venue.submit_count == 0
        result = asyncio.run(c.cycle(shared_frame()))
        assert result["status"] == "OPEN", result
        intent = intent_for(c.engine, result["client_id"])
        assert intent.exit_at == AT.replace(hour=19, minute=45)
        assert intent.order_expires_at == AT.replace(hour=20)
        with pytest.raises(ValidationError):
            swing_policy(holding_policy="OVERNIGHT")


def test_installed_cli_roundtrip_create_only_and_capacity(tmp_path):
    r = request()
    source, output = tmp_path / "request.json", tmp_path / "review.json"
    source.write_text(r.model_dump_json())

    def run(*args):
        return subprocess.run(
            [sys.executable, "-I", "-m", "app.options.swing_carry", *map(str, args)],
            capture_output=True,
            check=False,
            text=True,
            cwd=tmp_path,
            timeout=30,
        )

    result = run("review", source, output)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["evidence_status"] == "READY"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    saved = output.read_bytes()
    assert run("verify", output, "--request-hash", fingerprint(r)).returncode == 0
    assert run("verify", output, "--request-hash", "0" * 64).returncode == 2
    assert run("review", source, output).returncode == 2 and output.read_bytes() == saved
    assert run("review", source, "relative.json").returncode == 2
    source.write_text('{"at": 1, "at": 2}')
    assert run("review", source, tmp_path / "duplicate.json").returncode == 2
    source.write_text(" " * (MAX_BYTES + 1))
    assert run("review", source, tmp_path / "large.json").returncode == 2


def test_known_cost_budget_reduces_quantity_and_unknown_does_not_become_zero():
    r = request()
    ordinary = review_swing_carry(r).admission
    limited = changed(r, "account", daily_loss_available=D("410"))
    a = review_swing_carry(limited).admission
    assert a.quantity == ordinary.quantity - 1
    assert a.full_premium_loss <= 410 < ordinary.full_premium_loss
    exhausted = review_swing_carry(changed(r, "account", total_loss_available=D("1")))
    assert exhausted.evidence_status == "BLOCKED" and exhausted.admission.quantity == 0
    assert (
        review_swing_carry(changed(limited, "account", budgets_known=False)).admission.quantity == 0
    )


def test_catalyst_exact_deadline_and_one_second_short():
    r = request()
    deadline = review_swing_carry(r).proposed_exit_at
    r = changed(r, "item", catalyst=r.item.catalyst.model_copy(update={"valid_through": deadline}))
    assert review_swing_carry(r).evidence_status == "READY"
    r = changed(
        r,
        "item",
        catalyst=r.item.catalyst.model_copy(
            update={"valid_through": deadline - timedelta(seconds=1)}
        ),
    )
    assert "SWING_CARRY_CATALYST_HORIZON" in review_swing_carry(r).reasons


def test_contract_mapping_and_seed_history_remain_exact():
    r = request()
    changed_quote = changed(
        r,
        "quote",
        instrument=r.quote.instrument.model_copy(update={"instrument_id": "replacement"}),
    )
    assert "SWING_CONTRACT_LOCK_CHANGED" in review_swing_carry(changed_quote).reasons
    h = r.item.seed.history.model_copy(update={"source": "different-daily"})
    r = changed(r, "item", seed=r.item.seed.model_copy(update={"history": h}))
    assert "SWING_DAILY_HISTORY_BINDING_OR_COVERAGE" in review_swing_carry(r).reasons


def test_calendar_out_of_range_blocks_without_weekday_fallback():
    r = request().model_copy(update={"at": AT.replace(year=2099)})
    out = review_swing_carry(r)
    assert out.evidence_status == "BLOCKED" and "SWING_CARRY_CALENDAR_UNAVAILABLE" in out.reasons


def test_unavailable_calendar_during_buffer_review_blocks(monkeypatch):
    from exchange_calendars.errors import RequestedSessionOutOfBounds

    import app.options.swing_carry as module

    def unavailable(*_):
        raise RequestedSessionOutOfBounds(XNYSCalendar().calendar, False)

    monkeypatch.setattr(module, "_calendar_path", unavailable)
    assert "SWING_CARRY_CALENDAR_UNAVAILABLE" in review_swing_carry(request()).reasons


def test_schema_rejects_clock_and_policy_bypass():
    with pytest.raises(ValidationError):
        review_swing_carry(request().model_copy(update={"at": AT.replace(tzinfo=None)}))
    r = changed(request(), "swing", unfilled_lifecycle=None)
    assert "SWING_CARRY_ORIGINAL_TARGET_LIFECYCLE_REQUIRED" in review_swing_carry(r).reasons
    exported = export_swing_carry(request())
    exported["review"]["authority"] = 0
    with pytest.raises(ValueError, match="reproduce"):
        verify_swing_carry_export(exported, expected_request_hash=fingerprint(request()))
