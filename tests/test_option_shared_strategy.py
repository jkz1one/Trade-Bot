"""One owner/AI/account for Degen and locked next-session Swing opportunities."""

import asyncio
import json
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_degen_options import AT, frame, policies
from test_option_entry_coordination import fake_model
from test_option_entry_reasoning import packet_for
from test_option_execution import configuration, intent_for, ledger
from test_option_observer import app_for

from app.execution.economics import CostPolicy
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenCoordinator, DegenFrame
from app.options.degen import scan_degen
from app.options.engine import OptionExecution, fingerprint
from app.options.observer import OptionObserver
from app.options.selection import ContractMetadata
from app.options.swing import (
    CatalystEvidence,
    SwingDailyBar,
    SwingHistory,
    SwingInput,
    SwingPolicy,
    SwingSeed,
    scan_swing,
    seed_issues,
)
from app.options.venue import DurableOptionVenue
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def swing_policy(**changes):
    return SwingPolicy.model_validate(
        {
            "history_source": "fixture-daily",
            "catalyst_source": "fixture-catalyst",
            "daily_lookback": 3,
            "minimum_dte": 7,
            "maximum_dte": 45,
            "maximum_chase_fraction": ".0065",
            "stop_buffer_fraction": ".0001",
            "catalyst_max_age_seconds": 10,
            "family_priority": ("SWING", "DEGEN"),
        }
        | changes
    )


def swing_input(right="CALL", target=date(2026, 10, 9)):
    cal = XNYSCalendar().calendar
    previous = cal.previous_session(target.isoformat())
    sessions = [previous]
    for _ in range(2):
        sessions.insert(0, cal.previous_session(sessions[0]))
    bars = []
    for n, session in enumerate(sessions):
        close = D(597 + n)
        o, high, low = close - D(".2"), close + 1, close - 1
        if right == "PUT":
            o, high, low, close = 1200 - o, 1200 - low, 1200 - high, 1200 - close
        bars.append(
            SwingDailyBar(
                begins_at=cal.session_open(session).to_pydatetime(),
                closes_at=cal.session_close(session).to_pydatetime(),
                open=o,
                high=high,
                low=low,
                close=close,
                volume=100000,
                interpolated=False,
            )
        )
    before = bars[-1].closes_at + timedelta(seconds=1)
    at = cal.session_open(target.isoformat()).to_pydatetime() + timedelta(minutes=30)
    base = frame(right)
    expiry = cal.date_to_session((target + timedelta(days=7)).isoformat(), direction="next")
    end = cal.session_close(expiry).to_pydatetime()
    contract = base.quotes[0].instrument.contract.model_copy(
        update={
            "expiration": expiry.date(),
            "last_trading_at": end,
            "expires_at": end + timedelta(hours=1),
            "settles_at": end + timedelta(days=1),
        }
    )
    instrument = base.quotes[0].instrument.model_copy(
        update={
            "contract": contract,
            "instrument_id": "swing-locked-contract",
        }
    )
    return SwingInput(
        seed=SwingSeed(
            created_at=before,
            target_session=target,
            instrument=instrument,
            history=SwingHistory(
                symbol="SPY",
                source="fixture-daily",
                source_at=before,
                received_at=before,
                entitlement="REALTIME",
                complete=True,
                bars=tuple(bars),
            ),
        ),
        metadata=ContractMetadata(
            instrument=instrument,
            delta=".45" if right == "CALL" else "-.45",
            greek_provenance="OBSERVED",
            volume=500,
            open_interest=1000,
            source="fixture-chain",
            source_at=at,
            received_at=at,
            entitlement="REALTIME",
            complete=True,
        ),
        catalyst=CatalystEvidence(
            symbol="SPY",
            source="fixture-catalyst",
            source_at=at,
            received_at=at,
            entitlement="REALTIME",
            complete=True,
            status="CLEAR",
            valid_through=cal.session_close(target.isoformat()).to_pydatetime(),
        ),
    )


def shared_frame(right="CALL", item=None):
    f = frame(right)
    item = item or swing_input(right)
    return f.model_copy(
        update={
            "swing": (item,),
            "quotes": f.quotes
            + (f.quotes[0].model_copy(update={"instrument": item.seed.instrument}),),
        }
    )


@contextmanager
def owner(path, right="CALL", *, ai=False, priority=("SWING", "DEGEN")):
    _, limits, execution = configuration(
        right, **({"cost_policy": CostPolicy(total_budget="1", daily_budget=".1")} if ai else {})
    )
    venue = DurableOptionVenue(path / "venue.db", limits=limits, capital=execution.capital)
    times = [AT]
    setup, selection = policies()
    kwargs = {}
    if ai:
        key = path / "model.key"
        key.write_text("fixture-only\n")
        key.chmod(0o600)
        kwargs = {
            "judgment_limits": JudgmentLimits(),
            "key_file": key,
            "entry_policy": packet_for(right).policy,
        }
    with OptionExecution.open(
        path / "options.db", limits, execution, venue, now=AT, create=True
    ) as e:
        assert e.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        e.assess(None, None, now=AT)
        c = DegenCoordinator(
            e,
            setup,
            selection,
            clock=lambda: times[0],
            create=True,
            swing_policy=swing_policy(family_priority=priority),
            **kwargs,
        )
        yield c, venue, times


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("ai", [False, True])
def test_shared_owner_selects_swing_once_with_costs_and_independent_protection(
    tmp_path, monkeypatch, right, ai
):
    with owner(tmp_path, right, ai=ai) as (c, venue, _times):
        calls = fake_model(monkeypatch, c) if ai else []
        f = shared_frame(right)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        assert {x["family"] for x in result["candidates"]} == {
            "ORB_CONTINUATION",
            "SWING_DAILY_BREAKOUT",
        }
        intent = intent_for(c.engine, result["client_id"])
        assert intent.instrument == f.swing[0].seed.instrument
        assert intent.exit_at <= AT.replace(hour=19, minute=45)
        assert asyncio.run(c.cycle(f)) == result and venue.submit_count == 1
        assert len(calls) == int(ai)
        if ai:
            assert len(calls[0].packet.opportunities) == 2
            assert calls[0].packet.opportunities[0].scan.version == "swing-next-session-v1"
            with c.engine.journal.read() as db:
                assert D(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) == D(
                    ".00015"
                )
        venue.fill(intent, intent.quantity, f.quotes[1], AT, fill_id="swing-fill")
        assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        assert ledger(c.engine).position.contract == intent.instrument.contract
        held = c.quote_plan((), ())
        assert held["purpose"] == "HELD_OR_PENDING_CONTRACT" and held["instruments"] == (
            intent.instrument,
        )
        u = f.underlyings[0].model_copy(
            update={
                "bid": D(590) if right == "CALL" else D(610),
                "ask": D(590) if right == "CALL" else D(610),
            }
        )
        result = asyncio.run(c.supervise((f.quotes[1],), (u,)))
        # Fully filled entry allows the independent owner to submit only the close.
        assert result["status"] == "OPEN", result
        assert c.engine.assess(f.quotes[1], u, now=AT)["exit_reason"] == "UNDERLYING_INVALIDATION"
        assert len(calls) == int(ai)


def test_deterministic_priority_can_select_degen_in_joint_account(tmp_path):
    with owner(tmp_path, priority=("DEGEN", "SWING")) as (c, venue, _):
        result = asyncio.run(c.cycle(shared_frame()))
        assert result["status"] == "OPEN", result
        assert intent_for(c.engine, result["client_id"]).instrument == frame().quotes[0].instrument
        assert venue.submit_count == 1


@pytest.mark.parametrize(
    "target,previous",
    [
        (date(2026, 7, 6), date(2026, 7, 2)),
        (date(2026, 11, 30), date(2026, 11, 27)),
        (date(2026, 3, 9), date(2026, 3, 6)),
    ],
)
def test_next_actual_session_includes_holiday_half_day_and_dst(target, previous):
    item = swing_input(target=target)
    assert item.seed.history.bars[-1].closes_at.date() == previous
    assert seed_issues(item.seed, swing_policy(), XNYSCalendar(), ("SPY",)) == ()
    if previous.month == 11:
        assert item.seed.history.bars[-1].closes_at.hour == 18


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("late_seed", "SWING_SEED_NOT_KNOWN_BEFORE_TARGET_OPEN"),
        ("interpolated", "SWING_DAILY_BARS_INCOMPLETE_GAPPED_OR_INTERPOLATED"),
        ("gap", "SWING_DAILY_BARS_INCOMPLETE_GAPPED_OR_INTERPOLATED"),
        ("wrong_source", "SWING_DAILY_HISTORY_BINDING_OR_COVERAGE"),
        ("zero_dte", "SWING_LOCKED_CONTRACT_INELIGIBLE"),
        ("unknown_catalyst", "SWING_CATALYST_CLEARANCE_REQUIRED"),
        ("stale_catalyst", "SWING_CATALYST_CLEARANCE_REQUIRED"),
        ("short_clearance", "SWING_CATALYST_CLEARANCE_REQUIRED"),
        ("lock_changed", "SWING_CONTRACT_LOCK_CHANGED"),
        ("trend", "SWING_DAILY_TREND_REQUIRED"),
    ],
)
def test_bad_swing_evidence_cannot_confirm(damage, reason):
    item = swing_input()
    seed, h = item.seed, item.seed.history
    if damage == "late_seed":
        seed = seed.model_copy(update={"created_at": AT})
    elif damage in {"interpolated", "gap", "trend"}:
        bars = list(h.bars)
        bars[0] = (
            bars[0].model_copy(update={"interpolated": True})
            if damage == "interpolated"
            else bars[1]
            if damage == "gap"
            else bars[0].model_copy(update={"close": D(598)})
        )
        seed = seed.model_copy(update={"history": h.model_copy(update={"bars": tuple(bars)})})
    elif damage == "wrong_source":
        seed = seed.model_copy(update={"history": h.model_copy(update={"source": "other"})})
    elif damage == "zero_dte":
        seed = seed.model_copy(update={"instrument": frame().quotes[0].instrument})
    elif damage == "lock_changed":
        item = item.model_copy(
            update={
                "metadata": item.metadata.model_copy(
                    update={"instrument": frame().quotes[0].instrument}
                )
            }
        )
    else:
        update = (
            {"status": "UNKNOWN"}
            if damage == "unknown_catalyst"
            else {"valid_through": AT}
            if damage == "short_clearance"
            else {"source_at": AT - timedelta(seconds=60)}
        )
        item = item.model_copy(update={"catalyst": item.catalyst.model_copy(update=update)})
    item = item.model_copy(update={"seed": seed})
    f, cal = frame(), XNYSCalendar()
    intraday = scan_degen(f.histories[0], policies()[0], cal.current_window(AT), now=AT)
    s = scan_swing(
        item, swing_policy(), intraday, f.histories[0], cal, ("SPY",), now=AT, receive_lag=2
    )
    assert s.observations[0].status != "CONFIRMED"
    assert reason in s.observations[0].reasons


def test_seed_lock_cannot_change_across_cycles_or_restart(tmp_path):
    with owner(tmp_path) as (c, venue, _times):
        f = shared_frame()
        # Invalid current catalyst produces no Swing candidate but still freezes the seed.
        item = f.swing[0].model_copy(
            update={"catalyst": f.swing[0].catalyst.model_copy(update={"status": "UNKNOWN"})}
        )
        f = f.model_copy(update={"swing": (item,), "quotes": frame().quotes})
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result  # Degen remains independently eligible.
        with c.engine.journal.read() as db:
            assert db.execute("SELECT seed_hash FROM execution_option_swing_seeds").fetchone()[
                0
            ] == fingerprint(item.seed)
        saved = (c.engine.limits, c.engine.policy, c.policy, c.selection, c.swing_policy)
    limits, execution, setup, selection, swing = saved
    with OptionExecution.open(tmp_path / "options.db", limits, execution, venue, now=AT) as e:
        c = DegenCoordinator(e, setup, selection, swing_policy=swing, clock=lambda: AT)
        with e.journal.read() as db:
            assert db.execute("SELECT seed_hash FROM execution_option_swing_seeds").fetchone()[
                0
            ] == fingerprint(item.seed)
        from app.options.shared_strategy import lock_seeds

        changed = item.model_copy(
            update={
                "seed": item.seed.model_copy(
                    update={"created_at": item.seed.created_at + timedelta(seconds=1)}
                )
            }
        )
        with pytest.raises(ExecutionBlocked, match="SWING_SEED_LOCK_CONFLICT"):
            lock_seeds(c, (changed,))


def test_stored_observer_filters_families_without_work(tmp_path):
    with owner(tmp_path) as (c, venue, _):
        assert asyncio.run(c.cycle(shared_frame()))["status"] == "OPEN"
        observer = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        )
        for family, expected in [("SWING", "SWING_DAILY_BREAKOUT"), ("DEGEN", "ORB_CONTINUATION")]:
            report = observer.report(family=family)
            assert report["opportunities"][0]["candidates"][0]["setup"] == expected, report
        assert observer.report(family="SCOPE")["opportunities"] == []
        client, _ = app_for(c, tmp_path)
        with client:
            page = client.get("/?family=SWING")
        assert page.status_code == 200 and "SWING_DAILY_BREAKOUT" in page.text
        assert "Swing is not implemented" not in page.text and venue.submit_count == 1


def test_legacy_serialized_frames_and_enrollment_do_not_change(tmp_path):
    assert "swing" not in frame().model_dump() and "swing" not in DegenFrame().model_dump()
    from test_degen_options import owned_strategy

    with owned_strategy(tmp_path) as (c, *_):
        assert "swing" not in json.loads(c._frozen)
        with pytest.raises(ValueError, match="enrollment"):
            c.quote_plan(frame().histories, frame().inventories, (swing_input(),))


@pytest.mark.parametrize(
    "changes",
    [
        {"holding_policy": "OVERNIGHT"},
        {"minimum_dte": 0},
        {"maximum_dte": 5},
        {"family_priority": ("SWING", "SWING")},
        {"maximum_chase_fraction": 0.1},
    ],
)
def test_no_implicit_overnight_or_unbounded_family_policy(changes):
    with pytest.raises(ValidationError):
        swing_policy(**changes)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("phase", ["prepare", "dispatch"])
def test_current_chase_and_break_rechecked_before_every_order(tmp_path, monkeypatch, right, phase):
    with owner(tmp_path, right) as (c, venue, _):
        f = shared_frame(right)
        adverse = f.underlyings[0].model_copy(
            update={
                "bid": D(606) if right == "CALL" else D(594),
                "ask": D(606) if right == "CALL" else D(594),
            }
        )
        if phase == "prepare":
            f = f.model_copy(update={"underlyings": (adverse,)})
        else:
            original = c.engine.dispatch

            async def dispatch(client_id, quote, underlying, *, now):
                return await original(client_id, quote, adverse, now=now)

            monkeypatch.setattr(c.engine, "dispatch", dispatch)
        result = asyncio.run(c.cycle(f))
        assert result["status"] != "OPEN", result
        assert venue.submit_count == 0
        report = c.engine.journal.report(now=AT)
        assert "SWING_CURRENT_BREAK_OR_CHASE_REJECTED" in json.dumps(report)


def test_expired_catalyst_at_dispatch_never_reuses_old_clearance(tmp_path, monkeypatch):
    with owner(tmp_path) as (c, venue, _):
        # Expire clearance while keeping all executable quote and account clocks fresh.
        original = c.engine.dispatch

        async def dispatch(client_id, quote, underlying, *, now):
            with c.engine.journal.write() as db:
                row = db.execute(
                    "SELECT cycle_key,result_json FROM execution_option_opportunities"
                ).fetchone()
                data = json.loads(row[1])
                data["scans"][0]["catalyst"]["source_at"] = (AT - timedelta(seconds=20)).isoformat()
                data["scans"][0]["catalyst"]["received_at"] = (
                    AT - timedelta(seconds=20)
                ).isoformat()
                db.execute(
                    "UPDATE execution_option_opportunities SET result_json=? WHERE cycle_key=?",
                    (json.dumps(data), row[0]),
                )
            return await original(client_id, quote, underlying, now=now)

        monkeypatch.setattr(c.engine, "dispatch", dispatch)
        result = asyncio.run(c.cycle(shared_frame()))
        assert result["status"] != "OPEN" and venue.submit_count == 0
        assert "SWING_CATALYST_CLEARANCE_EXPIRED" in json.dumps(c.engine.journal.report(now=AT))


def test_unknown_shared_ai_cost_halts_both_families(tmp_path, monkeypatch):
    with owner(tmp_path, ai=True) as (c, venue, _):
        from app.options import entry_judgment

        async def failed(*args, **kwargs):
            raise RuntimeError("fixture provider timeout")

        monkeypatch.setattr(entry_judgment, "run_entry_process", failed)
        result = asyncio.run(c.cycle(shared_frame()))
        assert result["reason"] == "OPTION_MODEL_COST_UNKNOWN" and venue.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None
            assert c.engine._account(db, AT).entry_halted
        assert (
            c.quote_plan(frame().histories, frame().inventories, (swing_input(),))["purpose"]
            == "ENTRY_HEALTH_BLOCKED"
        )


def test_missing_swing_evidence_is_visible_and_never_silently_removed(tmp_path):
    with owner(tmp_path) as (c, venue, _):
        result = asyncio.run(c.cycle(frame()))
        assert result["blocker"] == "EXACT_SWING_SEED_COVERAGE_REQUIRED"
        assert result["families"] == ["DEGEN", "SWING"] and venue.submit_count == 0


def test_no_second_coordinator_or_frozen_policy_change(tmp_path):
    with owner(tmp_path) as (c, venue, _):
        with pytest.raises(ValueError, match="One active"):
            DegenCoordinator(c.engine, c.policy, c.selection, swing_policy=c.swing_policy)
        saved = c.engine.limits, c.engine.policy, c.policy, c.selection
    limits, execution, setup, selection = saved
    with (
        OptionExecution.open(tmp_path / "options.db", limits, execution, venue, now=AT) as e,
        pytest.raises(ExecutionBlocked, match="FROZEN"),
    ):
        DegenCoordinator(
            e, setup, selection, swing_policy=swing_policy(maximum_chase_fraction=".01")
        )


def test_joint_runtime_and_held_contract_feed_use_existing_single_owner(tmp_path):
    from test_option_runtime import enable, packet, policy, step

    from app.options.runtime import OptionRuntime

    with owner(tmp_path) as (c, venue, _):
        r = OptionRuntime(c, policy(tmp_path), create=True)
        enable(r)
        packet(r, value=shared_frame())
        asyncio.run(step(r))
        assert venue.submit_count == 1
        report = c.report()
        assert report["cycles"][0]["result"]["families"] == ["DEGEN", "SWING"]


def test_installed_runtime_init_roundtrip_joint_settings(tmp_path):
    import subprocess
    import sys

    from test_option_runtime import settings

    from app.options.runtime_cli import load

    s = settings(tmp_path).model_copy(update={"swing_policy": swing_policy()})
    source = tmp_path / "settings.json"
    source.write_text(s.model_dump_json())
    source.chmod(0o600)
    target = tmp_path / "joint"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.runtime_cli",
            "init",
            "--settings",
            str(source),
            "--directory",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert load(target / "runtime.json") == s
    assert json.loads(result.stdout)["live_enabled"] is False


def test_ai_may_choose_degen_from_same_joint_packet(tmp_path, monkeypatch):
    from test_option_entry_reasoning import plan_for

    with owner(tmp_path, ai=True) as (c, venue, _):

        def choose(request, result):
            degen = request.packet.opportunities[1]
            return result.model_copy(
                update={
                    "plan": plan_for(
                        request.packet,
                        candidate_id=degen.candidate.candidate_id,
                        evidence_ids=degen.evidence_ids,
                    )
                }
            )

        calls = fake_model(monkeypatch, c, changes=choose)
        result = asyncio.run(c.cycle(shared_frame()))
        assert result["status"] == "OPEN", result
        assert intent_for(c.engine, result["client_id"]).instrument == frame().quotes[0].instrument
        assert venue.submit_count == len(calls) == 1


def test_joint_native_model_worker_roundtrips_both_families(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    from test_option_entry_judgment import output_for

    from app.options.entry_judgment import create_request, run_entry_process

    with owner(tmp_path, ai=True) as (c, _, _times):
        calls = fake_model(monkeypatch, c)
        assert asyncio.run(c.cycle(shared_frame()))["status"] == "OPEN"
        request = create_request(
            calls[0].packet, calls[0].configuration, request_id="c" * 32, now=AT
        )
        output = output_for(request)
        spawn = asyncio.create_subprocess_exec
        source = (
            f"import sys; sys.path.insert(0,{str(Path(__file__).parent.parent)!r})\n"
            f"sys.path.insert(0,{str(Path(__file__).parent)!r})\n"
            "import app.options.entry_judgment_worker as worker\n"
            "from test_execution_judgment import sdk_client\n"
            f"worker.OpenAI=lambda **kw: sdk_client(output={output!r})[0]\n"
            "raise SystemExit(worker.main())\n"
        )

        async def isolated(*args, **kwargs):
            assert args == (sys.executable, "-I", "-m", "app.options.entry_judgment_worker")
            return await spawn(sys.executable, "-I", "-c", source, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", isolated)
        result = asyncio.run(run_entry_process(request, "fixture-only"))
        assert (
            result.error is None
            and result.plan.candidate_id == request.packet.opportunities[0].candidate.candidate_id
        )
        assert result.usage.input_tokens == 1000


def test_entry_packet_cannot_rebind_locked_swing_contract(tmp_path, monkeypatch):
    from app.options.entry_reasoning import EntryPacket

    with owner(tmp_path, ai=True) as (c, _, _times):
        calls = fake_model(monkeypatch, c)
        assert asyncio.run(c.cycle(shared_frame()))["status"] == "OPEN"
        packet = calls[0].packet.model_dump()
        opportunity = packet["opportunities"][0]
        opportunity["scan"]["seed"]["instrument"] = packet["opportunities"][1]["candidate"][
            "instrument"
        ]
        opportunity["evidence_ids"] = [
            fingerprint(opportunity[key]) for key in ("scan", "quote", "underlying")
        ]
        candidate = opportunity["candidate"]
        candidate["candidate_id"] = fingerprint(
            {
                "scan": opportunity["scan"],
                "instrument": candidate["instrument"],
                "family": candidate["family"],
                "quote": opportunity["quote"],
            }
        )
        with pytest.raises(ValueError, match="Exact confirmed setup"):
            EntryPacket.model_validate(packet)


def test_swing_blocker_is_visible_when_degen_is_eligible(tmp_path):
    with owner(tmp_path) as (c, _, _times):
        item = swing_input()
        item = item.model_copy(
            update={"catalyst": item.catalyst.model_copy(update={"status": "UNKNOWN"})}
        )
        f = frame().model_copy(update={"swing": (item,)})
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        client, _ = app_for(c, tmp_path)
        with client:
            page = client.get("/?family=SWING")
        assert "SWING_CATALYST_CLEARANCE_REQUIRED" in page.text and "BLOCKED" in page.text


def test_shared_quote_capacity_cannot_exceed_existing_owner(tmp_path):
    from test_option_runtime import settings

    from app.options.runtime_models import RuntimeSettings

    s = settings(tmp_path).model_dump()
    s["setup"]["symbols"] = ["SPY", "QQQ"]
    s["limits"]["allowed_underlyings"] = ["SPY", "QQQ"]
    s["selection"]["max_quote_contracts"] = 4
    s["swing_policy"] = swing_policy().model_dump()
    with pytest.raises(ValueError, match="universe"):
        RuntimeSettings.model_validate(s)
