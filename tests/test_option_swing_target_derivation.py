"""Automatic original risk objectives reach native lifecycle without changing old seeds."""

import asyncio
import copy
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import timedelta
from decimal import ROUND_UP, Decimal, localcontext

import pytest
from test_degen_options import AT, policies
from test_option_entry_coordination import fake_model
from test_option_entry_reasoning import packet_for
from test_option_execution import configuration, intent_for, ledger
from test_option_shared_strategy import shared_frame, swing_input, swing_policy
from test_option_swing_targets import touch

from app.execution.economics import CostPolicy
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.shared_strategy import lock_seeds
from app.options.swing import SwingPolicy, seed_issues
from app.options.swing_lifecycle import load_terminal
from app.options.swing_targets import (
    SwingSeedBuildRequest,
    build_seed_bundle,
    build_swing_seed,
    target_issues,
    verify_seed_bundle,
)
from app.options.venue import DurableOptionVenue
from app.robinhood.schedule import XNYSCalendar

D = Decimal


def request(right="CALL", *, seed=None, policy=None):
    seed = seed or swing_input(right).seed
    return SwingSeedBuildRequest(
        **seed.model_dump(exclude={"version", "first_target", "target_geometry"}),
        policy=policy
        or swing_policy(
            unfilled_lifecycle="observed-lifecycle-v3", target_derivation="original-risk-ladder-v1"
        ),
        symbols=("SPY",),
    )


def generated_frame(right="CALL", *, policy=None):
    item = swing_input(right)
    seed = build_swing_seed(request(right, seed=item.seed, policy=policy))
    return shared_frame(right, item.model_copy(update={"seed": seed}))


@contextmanager
def owner(path, right="CALL", *, ai=False, create=True, swing=None):
    _, limits, execution = configuration(
        right, **({"cost_policy": CostPolicy(total_budget="1", daily_budget=".1")} if ai else {})
    )
    swing = swing or request(right).policy
    venue = DurableOptionVenue(
        path / "venue.db", limits=limits, capital=execution.capital if create else None
    )
    setup, selection = policies()
    times = [AT]
    kwargs = {}
    if ai:
        key = path / "model.key"
        if create:
            key.write_text("fixture-only\n")
            key.chmod(0o600)
        kwargs = {
            "judgment_limits": JudgmentLimits(),
            "key_file": key,
            "entry_policy": packet_for(right).policy,
        }
    with OptionExecution.open(
        path / "options.db", limits, execution, venue, now=AT, create=create
    ) as engine:
        if create:
            assert engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
            engine.assess(None, None, now=AT)
        c = DegenCoordinator(
            engine,
            setup,
            selection,
            create=create,
            swing_policy=swing,
            clock=lambda: times[0],
            **kwargs,
        )
        yield c, venue, times


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("precision", [4, 28])
def test_original_three_objectives_ignore_ambient_decimal_context(right, precision):
    req = request(right)
    with localcontext() as context:
        context.prec = precision
        context.rounding = ROUND_UP
        seed = build_swing_seed(req)
    expected = (
        ("602.0598", "604.1196", "606.1794")
        if right == "CALL"
        else ("597.9398", "595.8796", "593.8194")
    )
    assert seed.target_geometry.targets == tuple(D(v) for v in expected)
    assert seed.first_target == D(expected[0])
    assert seed.target_geometry.policy_hash == fingerprint(req.policy)
    assert seed.created_at == req.created_at and seed.instrument == req.instrument
    assert not seed_issues(seed, req.policy, XNYSCalendar(), req.symbols)
    bundle = build_seed_bundle(req)
    assert verify_seed_bundle(bundle, bundle["bundle_hash"]) == seed


@pytest.mark.parametrize(
    "damage",
    [
        "late",
        "future-history",
        "source",
        "gap",
        "interpolated",
        "volume",
        "incomplete",
        "symbol",
        "contract",
        "carry",
    ],
)
def test_builder_rejects_unavailable_or_foreign_original_evidence(damage):
    r = request()
    raw = r.model_dump(mode="json")
    if damage == "late":
        raw["created_at"] = AT.isoformat()
    elif damage == "future-history":
        raw["history"]["received_at"] = AT.isoformat()
    elif damage == "source":
        raw["history"]["source"] = "foreign"
    elif damage == "gap":
        raw["history"]["bars"][0]["begins_at"] = raw["history"]["bars"][1]["begins_at"]
    elif damage == "interpolated":
        raw["history"]["bars"][0]["interpolated"] = True
    elif damage == "volume":
        raw["history"]["bars"][0]["volume"] = 0
    elif damage == "incomplete":
        raw["history"]["complete"] = False
    elif damage == "symbol":
        raw["symbols"] = ["QQQ"]
    elif damage == "contract":
        raw["instrument"]["contract"]["root"] = "QQQ"
    else:
        raw["carry_exit_session"] = "2026-10-12"
    with pytest.raises(ValueError):
        build_swing_seed(SwingSeedBuildRequest.model_validate(raw))


def test_nonpositive_put_objectives_are_rejected_without_shortening_ladder():
    r = request("PUT")
    bars = list(r.history.bars)
    bars[-1] = bars[-1].model_copy(update={"low": D(1), "high": D(10), "open": D(5), "close": D(4)})
    with pytest.raises(ValueError, match="all three objectives"):
        build_swing_seed(
            r.model_copy(update={"history": r.history.model_copy(update={"bars": tuple(bars)})})
        )


@pytest.mark.parametrize(
    "damage",
    [
        "first",
        "second",
        "risk",
        "input-hash",
        "policy-hash",
        "created",
        "contract",
        "missing",
        "policy",
        "unenrolled",
    ],
)
def test_native_seed_boundary_reconstructs_all_original_terms(damage):
    req = request()
    seed = build_swing_seed(req)
    policy = req.policy
    if damage == "first":
        seed = seed.model_copy(update={"first_target": D(605)})
    elif damage in {"second", "risk", "input-hash", "policy-hash"}:
        g = seed.target_geometry
        changes = {
            "second": {"targets": (g.targets[0], D(605), g.targets[2])},
            "risk": {"risk": D(1)},
            "input-hash": {"inputs_hash": "a" * 64},
            "policy-hash": {"policy_hash": "b" * 64},
        }
        seed = seed.model_copy(update={"target_geometry": g.model_copy(update=changes[damage])})
    elif damage == "created":
        seed = seed.model_copy(update={"created_at": seed.created_at + timedelta(seconds=1)})
    elif damage == "contract":
        seed = seed.model_copy(
            update={
                "instrument": seed.instrument.model_copy(update={"instrument_id": "replacement"})
            }
        )
    elif damage == "missing":
        seed = seed.model_copy(update={"target_geometry": None})
    elif damage == "policy":
        policy = policy.model_copy(update={"stop_buffer_fraction": D(".0002")})
    else:
        policy = policy.model_copy(update={"target_derivation": None})
    assert target_issues(seed, policy)
    assert seed_issues(seed, policy, XNYSCalendar(), req.symbols)


def test_legacy_serialization_and_explicit_targets_stay_unchanged():
    p = swing_policy(unfilled_lifecycle="observed-lifecycle-v3")
    seed = swing_input().seed.model_copy(update={"first_target": D(605)})
    assert "target_derivation" not in p.model_dump()
    assert "target_geometry" not in seed.model_dump()
    assert not seed_issues(seed, p, XNYSCalendar(), ("SPY",))
    with pytest.raises(ValueError):
        SwingSeedBuildRequest.model_validate(request().model_dump() | {"policy": p})
    with pytest.raises(ValueError):
        SwingPolicy.model_validate(request().policy.model_dump() | {"unfilled_lifecycle": None})


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_generated_objective_is_sticky_through_runtime_recovery_and_reopen(tmp_path, right):
    from test_option_runtime import enable, packet, policy, step

    from app.options.runtime import OptionRuntime

    f = generated_frame(right)
    with owner(tmp_path, right) as (c, v, _):
        lock_seeds(c, f.swing)
        runtime = OptionRuntime(c, policy(tmp_path), create=True)
        enable(runtime)
        packet(runtime, value=f.model_copy(update={"underlyings": (touch(f),)}))
        asyncio.run(step(runtime))
        asyncio.run(c.supervise((), f.underlyings))
        with c.engine.journal.read() as db:
            terminal = load_terminal(db, f.swing[0].seed)
            locked = db.execute("SELECT seed_json FROM execution_option_swing_seeds").fetchone()[0]
        assert terminal.status == "TARGET_CONSUMED"
        assert terminal.first_target == f.swing[0].seed.target_geometry.targets[0]
        assert json.loads(locked) == f.swing[0].seed.model_dump(mode="json")
        assert v.submit_count == 0
    with owner(tmp_path, right, create=False) as (c, _, _):
        scan = c.quote_plan(f.histories, (), f.swing)["scans"][0]
        assert scan.terminal == terminal
        assert scan.seed.target_geometry == f.swing[0].seed.target_geometry


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_paid_fresh_target_race_retains_bill_and_no_fill(tmp_path, monkeypatch, right):
    with owner(tmp_path, right, ai=True) as (c, v, _):
        f = generated_frame(right)
        calls = fake_model(monkeypatch, c)
        original = c.engine.prepare

        def prepare(key, proposal, quote=None, underlying=None, **kwargs):
            return original(key, proposal, quote, touch(f), **kwargs)

        monkeypatch.setattr(c.engine, "prepare", prepare)
        result = asyncio.run(c.cycle(f))
        assert result["status"] != "OPEN" and len(calls) == 1 and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert D(db.execute("SELECT cost FROM execution_model_calls").fetchone()[0]) == D(
                ".00015"
            )
            assert load_terminal(db, f.swing[0].seed).status == "TARGET_CONSUMED"


def test_unknown_paid_cost_and_original_seed_remain_retained(tmp_path, monkeypatch):
    with owner(tmp_path, ai=True) as (c, v, _):
        f = generated_frame()
        calls = fake_model(
            monkeypatch, c, changes=lambda req, result: result.model_copy(update={"usage": None})
        )
        result = asyncio.run(c.cycle(f))
        assert result["status"] != "OPEN" and len(calls) == 1 and v.submit_count == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT cost FROM execution_model_calls").fetchone()[0] is None
            assert json.loads(
                db.execute("SELECT seed_json FROM execution_option_swing_seeds").fetchone()[0]
            ) == f.swing[0].seed.model_dump(mode="json")


def test_native_fill_and_protection_keep_generated_original_stop(tmp_path):
    with owner(tmp_path) as (c, v, _):
        f = generated_frame()
        result = asyncio.run(c.cycle(f))
        assert result["status"] == "OPEN", result
        intent = intent_for(c.engine, result["client_id"])
        v.fill(intent, intent.quantity, f.quotes[1], AT, fill_id="derived-seed-fill")
        assert c.engine.reconcile(v.snapshot(AT), now=AT)["reconciled"]
        assert (
            ledger(c.engine).position.original_underlying_invalidation
            == f.swing[0].seed.target_geometry.invalidation
        )
        original = intent.exit_at
        u = f.underlyings[0].model_copy(update={"bid": D(590), "ask": D("590.01")})
        close = asyncio.run(c.supervise((f.quotes[1],), (u,)))
        assert close["status"] == "OPEN", close
        sell = intent_for(c.engine, close["client_id"])
        assert sell.side == "SELL" and sell.exit_at == original
        assert sell.closing_entry_client_id == intent.client_id


def test_derivation_enrollment_cannot_change_on_restart(tmp_path):
    with owner(tmp_path):
        pass
    plain = request().policy.model_copy(update={"target_derivation": None})
    with pytest.raises((ValueError, ExecutionBlocked)), owner(tmp_path, create=False, swing=plain):
        pass


@pytest.mark.parametrize("damage", ["target", "stop", "contract", "authority"])
def test_portable_seed_rejects_changed_evidence_even_with_rehashed_envelope(damage):
    bundle = build_seed_bundle(request())
    changed = copy.deepcopy(bundle)
    if damage == "target":
        changed["seed"]["target_geometry"]["targets"][1] = "999"
    elif damage == "stop":
        changed["seed"]["target_geometry"]["invalidation"] = "1"
    elif damage == "contract":
        changed["seed"]["instrument"]["instrument_id"] = "replacement"
    else:
        changed["authority"] = True
    changed["bundle_hash"] = fingerprint({k: v for k, v in changed.items() if k != "bundle_hash"})
    with pytest.raises(ValueError):
        verify_seed_bundle(changed, changed["bundle_hash"])


def test_installed_cli_generates_exact_create_only_seed_bundle(tmp_path):
    src, dst = tmp_path / "request.json", tmp_path / "seed.json"
    src.write_text(request().model_dump_json())
    command = [
        sys.executable,
        "-I",
        "-W",
        "error",
        "-m",
        "app.options.swing_targets",
        "--request",
        str(src),
        "--output",
        str(dst),
    ]
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONWARNINGS": "error"}
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, env=env, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    bundle = json.loads(dst.read_text())
    assert bundle == build_seed_bundle(request())
    assert verify_seed_bundle(bundle, bundle["bundle_hash"]) == build_swing_seed(request())
    again = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, env=env, timeout=30, check=False
    )
    assert again.returncode != 0 and json.loads(dst.read_text()) == bundle
