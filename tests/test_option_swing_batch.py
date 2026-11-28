"""Complete common-source family competition, native ownership and immutable batch locks."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_entry_coordination import fake_model
from test_option_execution import intent_for, ledger
from test_option_shared_strategy import shared_frame, swing_input
from test_option_swing_ma import ma_request
from test_option_swing_target_derivation import owner

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.swing import SwingPolicy
from app.options.swing_batch import (
    SwingBatchInput,
    batch_seeds,
    expand_batches,
    lock_batches,
    seed_lock,
    unique_instruments,
)
from app.options.swing_lifecycle import load_terminal
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def batch_frame(right="CALL", *, seed=None, policy=None, item=None):
    req = ma_request(right, seed=seed, policy=policy)
    p = req.policy.model_dump()
    p.update(
        family_batch="complete-family-batch-v1",
        daily_base={"hourly_source": req.policy.ma_pullback.hourly_source, "hourly_lookback": 54},
        ma_pullback=req.policy.ma_pullback.model_dump() | {"periods": (8, 21, 50)},
        higher_levels={
            "keys": (
                "previous_week_high",
                "previous_week_low",
                "previous_month_high",
                "previous_month_low",
                "weekly_open",
            )
        },
    )
    policy = SwingPolicy.model_validate(p)
    item = item or swing_input(right)
    other = swing_input("PUT" if right == "CALL" else "CALL", target=item.seed.target_session)
    # For carry fixtures reuse the selected contract's full expiry/clock identity.
    other_instrument = item.seed.instrument.model_copy(
        update={
            "instrument_id": item.seed.instrument.instrument_id + "-opposite",
            "contract": item.seed.instrument.contract.model_copy(
                update={"right": "PUT" if right == "CALL" else "CALL"}
            ),
        }
    )
    other_meta = other.metadata.model_copy(
        update={
            "instrument": other_instrument,
            "source_at": item.metadata.source_at,
            "received_at": item.metadata.received_at,
        }
    )
    instruments = (
        (item.seed.instrument, other_instrument)
        if right == "CALL"
        else (other_instrument, item.seed.instrument)
    )
    metadata = (item.metadata, other_meta) if right == "CALL" else (other_meta, item.metadata)
    batch = SwingBatchInput.model_validate(
        {
            "seed": {
                "created_at": req.created_at,
                "target_session": req.target_session,
                "history": req.history.model_dump() | {"version": "swing-batch-daily-v1"},
                "hourly_history": req.hourly_history,
                "instruments": instruments,
                "carry_exit_session": req.carry_exit_session,
            },
            "metadata": metadata,
            "catalyst": item.catalyst,
        }
    )
    f = shared_frame(right, item).model_copy(update={"swing": (), "swing_batches": (batch,)})
    return f, policy


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_complete_source_enumerates_every_enrolled_variant_without_cherry_picking(right):
    f, p = batch_frame(right)
    seed = f.swing_batches[0].seed
    children = batch_seeds(seed, p, XNYSCalendar(), ("SPY",))
    assert len(children) == 14
    assert len({fingerprint(s) for s in children}) == 14
    assert {s.batch_hash for s in children} == {fingerprint(seed)}
    assert all(s.history.bars == seed.history.bars for s in children)
    assert all(s.created_at == seed.created_at for s in children)
    assert {s.instrument for s in children} == set(seed.instruments)
    assert all(
        s.target_geometry.policy_hash == fingerprint(p) for s in children if s.target_geometry
    )
    assert len(f.model_dump_json().encode()) < 256 * 1024


@pytest.mark.parametrize(
    "damage",
    [
        "daily-source",
        "hourly-source",
        "future",
        "gap",
        "interpolated",
        "volume",
        "missing-hourly",
        "foreign-contract",
        "contract-order",
        "partial-period",
        "unenrolled",
    ],
)
def test_any_original_source_defect_rejects_whole_batch(tmp_path, damage):
    f, p = batch_frame()
    raw = f.swing_batches[0].model_dump()
    s = raw["seed"]
    if damage == "daily-source":
        s["history"]["source"] = "foreign"
    elif damage == "hourly-source":
        s["hourly_history"]["source"] = "foreign"
    elif damage == "future":
        s["history"]["source_at"] += timedelta(days=1)
    elif damage == "gap":
        s["history"]["bars"][0]["begins_at"] += timedelta(minutes=1)
    elif damage == "interpolated":
        s["hourly_history"]["bars"][0]["interpolated"] = True
    elif damage == "volume":
        s["history"]["bars"][0]["volume"] = 0
    elif damage == "missing-hourly":
        s["hourly_history"] = None
    elif damage == "foreign-contract":
        s["instruments"][0]["contract"]["underlying"] = "QQQ"
    elif damage == "contract-order":
        s["instruments"] = tuple(reversed(s["instruments"]))
    elif damage == "partial-period":
        s["history"]["bars"] = s["history"]["bars"][-56:-1]
    else:
        p = p.model_copy(update={"family_batch": None})
    with pytest.raises(ValueError):
        b = SwingBatchInput.model_validate(raw)
        batch_seeds(b.seed, p, XNYSCalendar(), ("SPY",))


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_joint_plans_keep_family_evidence_and_request_each_exact_contract_once(tmp_path, right):
    f, p = batch_frame(right)
    with owner(tmp_path, right, swing=p) as (c, v, _):
        planned = c.quote_plan(f.histories, f.inventories, swing_batches=f.swing_batches)
        scans = [s for s in planned["scans"] if s.version == "swing-next-session-v1"]
        assert len(scans) == 14
        assert len([s for s in scans if s.observations[0].status == "CONFIRMED"]) > 1
        assert len(planned["instruments"]) == len({i.instrument_id for i in planned["instruments"]})
        assert len(planned["instruments"]) < sum(len(p.instruments) for p in planned["plans"])
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_option_swing_batches").fetchone()
        assert v.submit_count == 0


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("ai", [False, True])
def test_joint_competition_enters_only_one_exact_family_and_native_exit(
    tmp_path, monkeypatch, right, ai
):
    f, p = batch_frame(right)
    with owner(tmp_path, right, swing=p, ai=ai) as (c, v, times):
        calls = fake_model(monkeypatch, c) if ai else []
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        assert (
            len({x["family"] for x in result["candidates"] if x["family"].startswith("SWING")}) > 1
        )
        buy = intent_for(c.engine, result["client_id"])
        v.fill(buy, buy.quantity, f.quotes[1], times[0], fill_id="joint-buy")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        held = ledger(c.engine).position
        assert held and v.submit_count == 1 and len(calls) == int(ai)
        with c.engine.journal.read() as db:
            from app.options.swing_execution import selected_scan

            scan = selected_scan(db, buy.source_key)
            assert scan.observations[0].family == buy.entry_lineage.setup
            assert scan.seed.instrument == buy.instrument
            assert seed_lock(db, scan.seed)[0] == fingerprint(scan.seed)
            assert (
                db.execute("SELECT count(*) FROM execution_option_swing_batches").fetchone()[0] == 1
            )
            assert (
                db.execute("SELECT count(*) FROM execution_option_swing_batch_seeds").fetchone()[0]
                == 14
            )
            assert not db.execute("SELECT 1 FROM execution_option_swing_seeds").fetchone()
        times[0] += timedelta(seconds=1)
        stop = held.original_underlying_invalidation
        u = f.underlyings[0].model_copy(
            update={
                "bid": stop - D(".01"),
                "ask": stop + D(".01"),
                "source_at": times[0],
                "received_at": times[0],
            }
        )
        q = f.quotes[1].model_copy(update={"source_at": times[0], "received_at": times[0]})
        close = asyncio.run(c.supervise((q,), (u,)))
        assert close["status"] == "OPEN", close
        sell = intent_for(c.engine, close["client_id"])
        v.fill(sell, sell.quantity, q, times[0], fill_id="joint-sell")
        assert c.engine.reconcile(v.snapshot(times[0]), now=times[0])["reconciled"]
        assert ledger(c.engine).position is None


@pytest.mark.parametrize(
    "damage", ["history", "contract", "creation", "missing-child", "child-source"]
)
def test_locked_batch_cannot_change_or_lose_children(tmp_path, damage):
    f, p = batch_frame()
    with owner(tmp_path, swing=p) as (c, _, _):
        lock_batches(c, f.swing_batches)
        child = expand_batches(f.swing_batches, p, c.engine.calendar, c.policy.symbols, c.now())[
            0
        ].seed
        if damage in ("missing-child", "child-source"):
            with c.engine.journal.write() as db:
                if damage == "missing-child":
                    db.execute(
                        "DELETE FROM execution_option_swing_batch_seeds WHERE seed_hash=?",
                        (fingerprint(child),),
                    )
                else:
                    raw = child.model_dump(mode="json")
                    raw["history"]["source"] = "foreign"
                    db.execute(
                        "UPDATE execution_option_swing_batch_seeds SET seed_json=? WHERE seed_hash=?",
                        (json.dumps(raw), fingerprint(child)),
                    )
            with c.engine.journal.read() as db, pytest.raises(ValueError, match="BATCH_CHANGED"):
                seed_lock(db, child)
        else:
            raw = f.swing_batches[0].model_dump()
            if damage == "history":
                raw["seed"]["history"]["bars"][0]["volume"] += 1
            elif damage == "creation":
                raw["seed"]["created_at"] += timedelta(seconds=1)
            else:
                raw["seed"]["instruments"][0]["instrument_id"] += "-changed"
                raw["metadata"][0]["instrument"]["instrument_id"] += "-changed"
            changed = SwingBatchInput.model_validate(raw)
            with pytest.raises(ExecutionBlocked, match="BATCH_LOCK_CONFLICT"):
                lock_batches(c, (changed,))
            with c.engine.journal.read() as db:
                assert seed_lock(db, child)


@pytest.mark.parametrize("missing", [True, False])
def test_incomplete_or_duplicate_batch_cannot_lock_any_source(tmp_path, missing):
    f, p = batch_frame()
    with owner(tmp_path, swing=p) as (c, _, _):
        with pytest.raises(ExecutionBlocked, match="BATCH_COVERAGE"):
            lock_batches(c, () if missing else f.swing_batches * 2)
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_option_swing_batches").fetchone()
            assert not db.execute("SELECT 1 FROM execution_option_swing_batch_seeds").fetchone()


def test_each_original_child_retirement_survives_runtime_and_restart(tmp_path):
    from test_option_runtime import enable, packet, step
    from test_option_runtime import policy as runtime_policy

    from app.options.runtime import OptionRuntime

    f, p = batch_frame()
    with owner(tmp_path, swing=p) as (c, v, _):
        lock_batches(c, f.swing_batches)
        children = batch_seeds(f.swing_batches[0].seed, p, c.engine.calendar, c.policy.symbols)
        child = next(
            s for s in children if s.ma_period == 8 and s.instrument.contract.right == "CALL"
        )
        u = f.underlyings[0].model_copy(
            update={"bid": child.first_target, "ask": child.first_target + D(".01")}
        )
        runtime = OptionRuntime(c, runtime_policy(tmp_path), create=True)
        enable(runtime)
        packet(runtime, value=f.model_copy(update={"underlyings": (u,)}))
        asyncio.run(step(runtime))
        with c.engine.journal.read() as db:
            terminal = load_terminal(db, child)
            assert terminal.status == "TARGET_CONSUMED"
        assert v.submit_count == 0
    with owner(tmp_path, swing=p, create=False) as (c, _, _), c.engine.journal.read() as db:
        assert load_terminal(db, child) == terminal and seed_lock(db, child)


def test_exact_shared_quote_alias_rejects_conflicting_instruments():
    from app.options.selection import ContractReadPlan

    f, _ = batch_frame()
    i = f.quotes[0].instrument
    p = ContractReadPlan(
        symbol="SPY",
        evaluated_at=f.underlyings[0].source_at,
        instruments=(i,),
        exclusions={},
        issues=(),
    )
    assert unique_instruments((p, p)) == (i,)
    other = i.model_copy(update={"contract": i.contract.model_copy(update={"right": "PUT"})})
    with pytest.raises(ValueError, match="Conflicting"):
        unique_instruments((p, p.model_copy(update={"instruments": (other,)})))


def test_unknown_joint_model_usage_remains_unknown(tmp_path, monkeypatch):
    f, p = batch_frame()
    with owner(tmp_path, swing=p, ai=True) as (c, v, _):
        fake_model(
            monkeypatch, c, changes=lambda req, result: result.model_copy(update={"usage": None})
        )
        result = asyncio.run(c.cycle(f))
        assert result["status"] != "OPEN" and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None


@pytest.mark.parametrize(
    "family", ["SWING_DAILY_8_EMA", "SWING_DAILY_21_EMA", "SWING_PREVIOUS_WEEK_HIGH"]
)
def test_paid_choice_can_select_a_different_family_with_same_contract(
    tmp_path, monkeypatch, family
):
    from test_option_entry_reasoning import plan_for

    from app.options.swing_execution import selected_scan

    f, p = batch_frame()
    with owner(tmp_path, swing=p, ai=True) as (c, v, _):

        def choose(request, result):
            opportunity = next(
                o for o in request.packet.opportunities if o.candidate.family == family
            )
            return result.model_copy(
                update={
                    "plan": plan_for(
                        request.packet,
                        candidate_id=opportunity.candidate.candidate_id,
                        evidence_ids=opportunity.evidence_ids,
                    )
                }
            )

        fake_model(monkeypatch, c, changes=choose)
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        buy = intent_for(c.engine, result["client_id"])
        with c.engine.journal.read() as db:
            assert selected_scan(db, buy.source_key).observations[0].family == family
        assert buy.entry_lineage.setup == family and v.submit_count == 1


def test_fresh_post_cost_rejection_does_not_erase_joint_entry_charge(tmp_path, monkeypatch):
    f, p = batch_frame()
    with owner(tmp_path, swing=p, ai=True) as (c, v, _):
        calls = fake_model(monkeypatch, c)
        prepare = c.engine.prepare

        def changed(key, proposal, quote=None, underlying=None, **kwargs):
            return prepare(
                key,
                proposal,
                quote,
                underlying.model_copy(update={"bid": D(650), "ask": D("650.01")}),
                **kwargs,
            )

        monkeypatch.setattr(c.engine, "prepare", changed)
        result = asyncio.run(c.cycle(f))
        assert result["status"] != "OPEN" and len(calls) == 1 and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert D(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) == D(
                ".00015"
            )


def test_joint_observer_reads_competing_evidence_without_acting(tmp_path):
    from app.options.observer import OptionObserver

    f, p = batch_frame()
    with owner(tmp_path, swing=p) as (c, v, _):
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        before = v.submit_count
        report = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
        assert len(report["opportunities"][0]["setup_observations"]) >= 14
        assert v.submit_count == before


def test_joint_journal_bound_does_not_relax_legacy_or_model_limits():
    from app.options import entry_judgment, judgment
    from app.options.observer import MAX_RECORD_BYTES, _json
    from app.options.swing_batch import stored_result

    assert entry_judgment.MAX_REQUEST_BYTES == judgment.MAX_REQUEST_BYTES == 256 * 1024
    assert MAX_RECORD_BYTES == 256 * 1024
    with pytest.raises(ValueError):
        _json(json.dumps({"padding": "x" * (MAX_RECORD_BYTES + 1)}))
    with pytest.raises(ValueError):
        stored_result("x" * (4 * 1024 * 1024 + 1))


def test_missing_quote_preserves_readable_complete_blocked_cycle(tmp_path):
    from app.options.observer import OptionObserver

    f, p = batch_frame()
    with owner(tmp_path, swing=p) as (c, v, _):
        result = asyncio.run(c.cycle(f.model_copy(update={"quotes": ()})))
        assert (
            result["status"] == "HOLD"
            and result["reason"] == "EXACT_REQUESTED_QUOTE_COVERAGE_REQUIRED"
        )
        report = OptionObserver(
            c.engine.journal.path, c.engine.limits.population_id, clock=c.clock
        ).report()
        assert report["opportunities"][0]["status"] == "HOLD" and v.submit_count == 0


def test_unenrolled_batch_rejected_before_slot_or_order(tmp_path):
    from test_option_shared_strategy import owner as legacy_owner

    f, _ = batch_frame()
    with legacy_owner(tmp_path) as (c, v, _):
        with pytest.raises(ValueError, match="enrollment"):
            asyncio.run(c.cycle(f))
        with c.engine.journal.read() as db:
            assert not db.execute("SELECT 1 FROM execution_option_opportunities").fetchone()
        assert v.submit_count == 0


def test_second_symbol_conflict_rolls_back_first_new_root(tmp_path):
    from test_degen_options import AT, policies
    from test_option_execution import configuration

    from app.options.coordinator import DegenCoordinator
    from app.options.engine import OptionExecution
    from app.options.venue import DurableOptionVenue

    f, p = batch_frame()
    raw = f.swing_batches[0].model_dump()
    raw["seed"]["history"]["symbol"] = "QQQ"
    raw["seed"]["hourly_history"]["symbol"] = "QQQ"
    raw["catalyst"]["symbol"] = "QQQ"
    for instrument in raw["seed"]["instruments"]:
        instrument["instrument_id"] += "-QQQ"
        instrument["contract"].update(underlying="QQQ", root="QQQ")
    for m, instrument in zip(raw["metadata"], raw["seed"]["instruments"], strict=True):
        m["instrument"] = instrument
    qqq = SwingBatchInput.model_validate(raw)
    _, limits, execution = configuration()
    limits = limits.model_copy(update={"allowed_underlyings": ("SPY", "QQQ")})
    setup, selection = policies()
    setup = setup.model_copy(update={"symbols": ("SPY", "QQQ")})
    selection = selection.model_copy(update={"max_quote_contracts": 2})
    venue = DurableOptionVenue(tmp_path / "venue.db", limits=limits, capital=execution.capital)
    with OptionExecution.open(
        tmp_path / "options.db", limits, execution, venue, now=AT, create=True
    ) as engine:
        assert engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        engine.assess(None, None, now=AT)
        c = DegenCoordinator(
            engine, setup, selection, create=True, swing_policy=p, clock=lambda: AT
        )
        lock_batches(c, (*f.swing_batches, qqq))
        # Leave only the second symbol locked, then submit a new first root followed
        # by a conflicting second root. The whole write must roll back.
        with engine.journal.write() as db:
            digest = fingerprint(f.swing_batches[0].seed)
            db.execute(
                "DELETE FROM execution_option_swing_batch_seeds WHERE batch_hash=?", (digest,)
            )
            db.execute("DELETE FROM execution_option_swing_batches WHERE symbol='SPY'")
        raw = qqq.model_dump()
        raw["seed"]["history"]["bars"][0]["volume"] += 1
        with pytest.raises(ExecutionBlocked, match="BATCH_LOCK_CONFLICT"):
            lock_batches(c, (*f.swing_batches, SwingBatchInput.model_validate(raw)))
        with engine.journal.read() as db:
            assert [
                r[0] for r in db.execute("SELECT symbol FROM execution_option_swing_batches")
            ] == ["QQQ"]
            assert (
                db.execute("SELECT count(*) FROM execution_option_swing_batch_seeds").fetchone()[0]
                == 14
            )
        assert venue.submit_count == 0


def test_choice_only_batch_packet_has_explicit_contract_and_exact_family_join(tmp_path):
    from app.options.judgment import JointCandidatePacket, SharedCandidatePacket
    from app.options.selection import parse_candidate
    from app.options.swing_batch import scan_matches

    f, p = batch_frame()
    with owner(tmp_path, swing=p) as (c, _, _):
        plan = c.quote_plan(f.histories, f.inventories, swing_batches=f.swing_batches)
        with c.engine.journal.read() as db:
            account = c.engine._account(db, c.now())
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN"
        candidates = tuple(parse_candidate(v) for v in result["candidates"])
        scans = tuple(s for s in plan["scans"] if any(scan_matches(s, v) for v in candidates))
        packet = JointCandidatePacket(
            cycle_key=result["cycle_key"],
            as_of=c.now(),
            candidates=candidates,
            scans=scans,
            account=account,
            limits=c.engine.limits,
        )
        assert JointCandidatePacket.model_validate_json(packet.model_dump_json()) == packet
        with pytest.raises(ValueError):
            SharedCandidatePacket.model_validate(packet.model_dump())
        raw = packet.model_dump()
        raw["scans"] = tuple(s for s in raw["scans"] if s.get("version") != "swing-next-session-v1")
        with pytest.raises(ValueError, match="Exact joint"):
            JointCandidatePacket.model_validate(raw)


@pytest.mark.parametrize("quotes", [2, 3])
def test_runtime_capacity_reserves_both_original_swing_contracts_before_creation(tmp_path, quotes):
    from test_option_runtime import settings

    from app.options.runtime_models import RuntimeSettings

    _, p = batch_frame()
    raw = settings(tmp_path).model_dump()
    raw.update(swing_policy=p)
    raw["limits"]["allowed_underlyings"] = ("SPY", "QQQ")
    raw["setup"]["symbols"] = ("SPY", "QQQ")
    raw["selection"]["max_quote_contracts"] = quotes
    if quotes == 3:
        with pytest.raises(ValueError, match="universe"):
            RuntimeSettings.model_validate(raw)
    else:
        assert RuntimeSettings.model_validate(raw).swing_policy == p
