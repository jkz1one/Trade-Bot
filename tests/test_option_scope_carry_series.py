"""Combined replay retains original overnight holdings, isolated costs and fixed roles."""

import asyncio
import copy
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_option_entry_reasoning import packet_for
from test_option_scope_market_tape import record
from test_option_scope_trading_replay import request as baseline
from test_option_swing_execution import carry_frame, settings

from app.execution.economics import CostPolicy
from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.lifecycle import FamilyLossPolicy, NativeLossPolicy
from app.options.market_tape import TapeHeader
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.scope_carry_replay_model import ScopeCarryScript, ScopeCarryShortlistScript
from app.options.scope_carry_series import (
    ScopeCarryComparison,
    ScopeCarryGap,
    ScopeCarryModelReplay,
    ScopeCarrySeries,
    ScopeCarryTradingReplay,
    run_scope_carry_series,
    verify_scope_carry_series,
)
from app.options.scope_series import ScopeSeries
from app.options.scope_tape_watch import ScopeTapeWatchAction


def request(
    root,
    *,
    family="SWING",
    missing_gap=False,
    unknown=False,
    open_end=False,
    late_open=False,
    scope_unfilled=False,
):
    old = baseline(root)
    first = next(e for e in old.tape.events if e.kind == "CYCLE")
    at = first.recorded_at
    _, swing, _ = settings()
    raw = carry_frame().model_dump(mode="json")

    def align(v):
        if isinstance(v, list):
            return [align(x) for x in v]
        if isinstance(v, dict):
            return {
                k: "fixture-provider"
                if k == "provider"
                else "fixture-quote"
                if k == "source" and "instrument" in v and "bid" in v
                else align(x)
                for k, x in v.items()
            }
        return v

    source = DegenFrame.model_validate(align(raw))
    item = source.swing[0]
    item = item.model_copy(
        update={
            "metadata": item.metadata.model_copy(update={"source_at": at, "received_at": at}),
            "catalyst": item.catalyst.model_copy(update={"source_at": at, "received_at": at}),
        }
    )
    quote = source.quotes[1]
    underlying = source.underlyings[0]

    def market(when, *, scope=False):
        quotes = [quote.model_copy(update={"source_at": when, "received_at": when})]
        underlyings = [underlying.model_copy(update={"source_at": when, "received_at": when})]
        if scope:
            quotes.append(
                first.frame.scope.frame.quote.model_copy(
                    update={"source_at": when, "received_at": when}
                )
            )
            underlyings.append(
                first.frame.scope.underlying.model_copy(
                    update={"source_at": when, "received_at": when}
                )
            )
        return DegenFrame(quotes=tuple(quotes), underlyings=tuple(underlyings))

    header = old.tape.header.model_copy(update={"swing": swing})
    frames = [(e.recorded_at, e.kind, e.frame) for e in old.tape.events if e.recorded_at < at]
    current = first.frame.model_copy(
        update={
            "inventories": (),
            "swing": (item,),
            "quotes": market(at).quotes,
            "underlyings": market(at).underlyings,
        }
    )
    frames.append((at, "CYCLE", current))
    # Delivered observations advance before the synthetic paid completion.
    from test_option_scope_arming import refresh
    from test_option_scope_context import bind

    when = at + timedelta(seconds=1)
    f, ctx = refresh(first.frame.scope.frame, when)
    ctx = ctx.model_copy(
        update={
            "prior": first.frame.scope.context.prior,
            "previous_session": first.frame.scope.context.previous_session,
        }
    )
    updated = first.frame.scope.model_copy(
        update={
            "frame": bind(f, ctx),
            "context": ctx,
            "underlying": first.frame.scope.underlying.model_copy(
                update={"source_at": when, "received_at": when}
            ),
        }
    )
    frames.append((when, "SCOPE", DegenFrame(scope=updated)))
    frames.append((when, "MARKET", market(when, scope=True)))
    frames.append(
        (at + timedelta(seconds=2), "MARKET", market(at + timedelta(seconds=2), scope=True))
    )
    protect = header.scope.session.protect_at
    for when in (protect, protect + timedelta(seconds=1), header.closes_at):
        if scope_unfilled and when == protect + timedelta(seconds=1):
            continue
        frames.append((when, "MARKET", market(when, scope=True)))
    tape = record(root / "carry-first.tape", header, frames)
    actions = old.watch_actions + (
        ScopeTapeWatchAction(key="carry-cutoff", kind="ADVANCE", at=protect, play_key="first"),
    )
    shift = timedelta(days=3)
    session = header.scope.session
    later_session = session.model_copy(
        update={
            "session_date": session.session_date + shift,
            **{
                k: getattr(session, k) + shift
                for k in (
                    "opens_at",
                    "closes_at",
                    "protect_at",
                    "entry_starts_at",
                    "entry_cutoff_at",
                )
            },
        }
    )
    later_header = TapeHeader.model_validate(
        header.model_dump()
        | {
            "session_key": str(later_session.session_date),
            "opens_at": header.opens_at + shift,
            "closes_at": header.closes_at + shift,
            "scope": header.scope.model_copy(update={"session": later_session}),
        }
    )
    manage = at.replace(second=0, microsecond=0) + shift
    exit_at = (at + shift).replace(hour=19, minute=40, second=0, microsecond=0)
    first_quote = later_header.opens_at + timedelta(seconds=1 if late_open else 0)
    later_frames = [(first_quote, "MARKET", market(first_quote))]
    from test_option_scope_carry import next_session

    later_frames.append(
        (manage, "CYCLE", next_session(current, manage))
        if family == "SWING"
        else (manage, "MARKET", market(manage))
    )
    for when in (
        manage + timedelta(seconds=1),
        manage + timedelta(seconds=2),
        exit_at,
        exit_at + timedelta(seconds=1),
        later_header.closes_at,
    ):
        later_frames.append((when, "MARKET", market(when)))
    if open_end:
        later_frames = [e for e in later_frames if e[0] <= exit_at]
    later = record(root / "carry-last.tape", later_header, later_frames)
    loss = NativeLossPolicy(
        max_consecutive_losses=2,
        cooldown_seconds=1800,
        families=tuple(
            FamilyLossPolicy(family=f, max_consecutive_losses=2, cooldown_seconds=1800)
            for f in ("DEGEN", "SWING", "SCOPE")
        ),
    )
    execution = old.execution.model_copy(
        update={
            "swing_carry": "bounded-swing-carry-v1",
            "scope_carry": "shared-scope-carry-v1",
            "loss_control": loss,
        }
    )
    scope = old.scope.model_copy(
        update={
            "scope_carry": "shared-scope-carry-v1",
            "family_priority": (family, *[v for v in ("SCOPE", "SWING", "DEGEN") if v != family]),
        }
    )
    entry = packet_for().policy.model_copy(
        update={
            "scope_selection": "scope-fixed-plan-v1",
            "scope_carry": "shared-scope-carry-v1",
            "max_carry_horizon_seconds": 600000,
        }
    )
    selection = {"scope": True} if family == "SCOPE" else {"scope": False, "candidate_index": 0}
    choice = {"cycle_key": first.cycle_key, "delay_seconds": 1, **selection}
    geometry = (
        {}
        if family == "SCOPE"
        else {
            "condition": "NOW",
            "underlying_invalidation": "600",
            "underlying_target": "605",
            "horizon_seconds": int((exit_at - at).total_seconds()),
        }
    )
    decision = choice | {"action": "ENTER", **geometry}
    dmanage = {
        "cycle_key": "position:" + str(int(manage.timestamp()) // 300),
        "delay_seconds": 1,
        "action": "MAINTAIN" if open_end else "EXIT_ALL",
    }
    arms = {}
    for arm, name in zip("ABCD", ("baseline", "shortlist", "entry", "managed"), strict=True):
        kwargs = {
            "tape": tape,
            "limits": old.limits.model_copy(
                update={"population_id": "carry-" + arm, "account_id": "carry-account-" + arm}
            ),
            "execution": execution,
            "scope": scope,
            "watch_actions": actions,
            "data_cost": ".01",
            "host_cost": ".02",
        }
        if arm == "A":
            arms[name] = ScopeCarryTradingReplay(**kwargs)
        else:
            kwargs.update(
                execution=execution.model_copy(
                    update={
                        "scope_arbitration": "shared-scope-entry-v1",
                        "cost_policy": CostPolicy(total_budget="1", daily_budget=".1"),
                    }
                ),
                scope=scope.model_copy(update={"version": "shared-scope-entry-v1"}),
                entry_policy=entry.model_copy(
                    update={
                        "scope_selection": "scope-fixed-shortlist-v1"
                        if arm == "B"
                        else "scope-fixed-plan-v1",
                        "scope_carry_shortlist": "scope-carry-shortlist-v1" if arm == "B" else None,
                    }
                ),
                judgment_limits=JudgmentLimits(
                    process_timeout_seconds=5, request_timeout_seconds=3
                ),
                script=ScopeCarryShortlistScript(
                    decisions=(
                        {"cycle_key": first.cycle_key, "delay_seconds": 1, "action": "UNKNOWN"},
                    )
                    if unknown
                    else (choice | {"action": "SELECT"},)
                )
                if arm == "B"
                else ScopeCarryScript(
                    arm=arm,
                    decisions=(decision, *([dmanage] if arm == "D" and family == "SWING" else [])),
                ),
                position_policy=PositionReasoningPolicy(
                    max_lease_seconds=5,
                    scope_management="scope-fixed-position-v1",
                    swing_carry="bounded-swing-carry-v1",
                    scope_carry="shared-scope-carry-v1",
                )
                if arm == "D"
                else None,
            )
            arms[name] = ScopeCarryModelReplay(**kwargs)
    first_request = ScopeCarryComparison(**arms)
    later_actions = (
        ScopeTapeWatchAction(
            key="later-advance", kind="ADVANCE", at=later_header.opens_at, play_key="first"
        ),
    )
    last = ScopeCarryComparison(
        **{
            name: r.model_copy(update={"tape": later, "watch_actions": later_actions})
            for name, r in arms.items()
        }
    )
    return ScopeCarrySeries(
        sessions=(first_request, last),
        gaps=(
            ScopeCarryGap(
                starts_at=header.closes_at,
                ends_at=later_header.opens_at,
                data_cost=".03",
                host_cost=None if missing_gap else ".04",
            ),
        ),
    )


@pytest.fixture(scope="module", params=["SWING", "SCOPE"])
def replayed(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("scope-carry-series-" + request.param)
    req = globals()["request"](root, family=request.param)
    result = asyncio.run(run_scope_carry_series(req, root / "run"))
    bundle = json.loads((root / "run/series.json").read_text())
    return req, result, bundle


def test_independent_carry_and_scope_paths_with_full_cost_export(replayed):
    req, result, bundle = replayed
    assert result["comparison_complete"], result
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == result
    assert (
        len({v["population_id"] for v in (b["report"] for b in bundle["boundaries"][0].values())})
        == 4
    )
    for arm in "ABCD":
        first, last = [b[arm] for b in bundle["boundaries"]]
        buys = [
            json.loads(v[3])
            for v in last["evidence"]["execution_orders"]
            if json.loads(v[3])["side"] == "BUY"
        ]
        assert len(buys) == 1
        buy = buys[0]
        assert buy["entry_lineage"]["family"] == req.sessions[0].baseline.scope.family_priority[0]
        assert last["report"]["ledger"]["position"] is None
        period = result["carry_period_accounting"][arm]
        assert Decimal(period["data_cost"]) == Decimal(".05")
        assert Decimal(period["host_cost"]) == Decimal(".08")
        assert Decimal(period["net_after_all_costs"]) == Decimal(
            last["report"]["ledger"]["cash"]
        ) - req.sessions[0].baseline.execution.capital - Decimal(
            period["model_costs"]["known_cost"]
        ) - Decimal(".13")
        calls = last["evidence"]["execution_model_calls"]
        assert len(calls) == (
            0
            if arm == "A"
            else 2
            if arm == "D" and buy["entry_lineage"]["family"] == "SWING"
            else 1
        )
        if buy["entry_lineage"]["family"] == "SWING":
            assert first["report"]["ledger"]["position"]["swing_carry"] == buy["swing_carry"]
            assert not result["sessions"][0]["comparison_complete"]
            assert (
                result["overnight_intervals"][0]["accounts"][arm]["coverage"]
                == "NOT_CONTINUOUSLY_OBSERVED"
            )
        else:
            assert first["report"]["ledger"]["position"] is None
        assert period["benchmark_comparison"] is None
        assert result["net_return_difference_vs_spy"][arm] is None


@pytest.mark.parametrize(
    "damage", ["gap-time", "gap-count", "owner", "cost", "script", "legacy", "carry", "management"]
)
def test_frozen_carry_contract_rejects_changed_inputs(tmp_path, damage):
    req = request(tmp_path)
    raw = req.model_dump(mode="json")
    if damage == "gap-time":
        raw["gaps"][0]["ends_at"] = raw["gaps"][0]["starts_at"]
    elif damage == "gap-count":
        raw["gaps"] = []
    elif damage == "owner":
        raw["sessions"][1]["entry"]["limits"]["account_id"] = "different"
    elif damage == "cost":
        raw["sessions"][0]["entry"]["host_cost"] = ".03"
    elif damage == "script":
        raw["sessions"][0]["managed"]["script"]["decisions"][0]["delay_seconds"] = 2
    elif damage == "legacy":
        raw["sessions"][0]["entry"]["script"]["version"] = "scripted-scope-judgment-v1"
    elif damage == "carry":
        raw["sessions"][0]["entry"]["execution"].pop("scope_carry")
    else:
        raw["sessions"][0]["managed"]["position_policy"].pop("swing_carry")
    with pytest.raises(ValueError):
        ScopeCarrySeries.model_validate(raw)
    with pytest.raises(ValueError):
        ScopeSeries.model_validate(req.model_dump())


@pytest.mark.parametrize("damage", ["total", "terms", "cost", "policy"])
def test_detached_carry_reconstruction_rejects_tampering(replayed, damage):
    _, _, source = replayed
    b = copy.deepcopy(source)
    if damage == "total":
        b["report"]["carry_period_accounting"]["A"]["net_after_all_costs"] = "9"
    elif damage == "terms":
        row = b["boundaries"][-1]["A"]["evidence"]["execution_orders"][0]
        intent = json.loads(row[3])
        intent["exit_at"] = "2026-10-13T19:40:00Z"
        row[3] = json.dumps(intent)
    elif damage == "cost":
        b["request"]["gaps"][0]["host_cost"] = "0"
    else:
        b["request"]["sessions"][0]["shortlist"]["entry_policy"]["scope_selection"] = (
            "scope-fixed-plan-v1"
        )
    b["series_hash"] = fingerprint({k: v for k, v in b.items() if k != "series_hash"})
    with pytest.raises(ValueError):
        verify_scope_carry_series(b, b["series_hash"])


@pytest.mark.parametrize("kind", ["unknown-gap", "unknown-model", "open-end"])
def test_missing_cost_or_unresolved_exposure_never_becomes_comparable(tmp_path, kind):
    req = request(
        tmp_path,
        missing_gap=kind == "unknown-gap",
        unknown=kind == "unknown-model",
        open_end=kind == "open-end",
    )
    result = asyncio.run(run_scope_carry_series(req, tmp_path / "run"))
    assert not result["comparison_complete"]
    assert all(v is None for v in result["net_difference_vs_a"].values())
    final = result["sessions"][-1]["accounts"]
    if kind == "unknown-gap":
        assert all(a["native"]["host_cost"] is None for a in final.values())
        assert all(a["native"]["net_after_all_costs"] is None for a in final.values())
        assert all(a["closing"]["position"] is None for a in final.values())
    elif kind == "unknown-model":
        assert final["B"]["native"]["model_costs"]["unknown_calls"] == 1
        assert final["B"]["native"]["net_after_all_costs"] is None
        assert all(final[a]["native"]["net_after_all_costs"] is not None for a in "ACD")
    else:
        assert all(a["closing"]["position"] for a in final.values())
        assert all(a["native"]["net_after_all_costs"] is None for a in final.values())
    bundle = json.loads((tmp_path / "run/series.json").read_text())
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == result


def test_missing_opening_quote_keeps_native_halt_and_mandatory_exit(tmp_path):
    req = request(tmp_path, late_open=True)
    result = asyncio.run(run_scope_carry_series(req, tmp_path / "run"))
    bundle = json.loads((tmp_path / "run/series.json").read_text())
    for arm in "ABCD":
        exported = bundle["boundaries"][-1][arm]
        assert exported["report"]["ledger"]["position"] is None
        control = exported["evidence"]["execution_control"][0]
        assert control[3] == 1 and control[4] == "OPTION_UNPRICED_OR_STALE"
        orders = [json.loads(v[3]) for v in exported["evidence"]["execution_orders"]]
        assert any(o["side"] == "SELL" and "TIME_EXIT" in o["thesis"] for o in orders)
    assert len(bundle["boundaries"][-1]["D"]["evidence"]["execution_model_calls"]) == 1
    assert result["overnight_intervals"][0]["accounts"]["D"]["overnight_return"] is None


def test_unfilled_scope_close_retains_original_intraday_ownership(tmp_path):
    req = request(tmp_path, family="SCOPE", scope_unfilled=True)
    result = asyncio.run(run_scope_carry_series(req, tmp_path / "run"))
    assert not result["comparison_complete"]
    assert all(v is None for v in result["net_difference_vs_a"].values())
    for arm in "ABCD":
        gap = result["overnight_intervals"][0]["accounts"][arm]
        assert gap["ownership_status"] == "UNRESOLVED_INTRADAY_EXPOSURE"
        assert gap["position"].get("swing_carry") is None
        final = result["sessions"][-1]["accounts"][arm]
        assert final["closing"]["position"]["entry_client_id"] == gap["position"]["entry_client_id"]
        assert final["closing"]["position"]["exit_at"] == gap["position"]["exit_at"]
        assert final["native"]["net_after_all_costs"] is None
        assert final["native"]["model_costs"]["unknown_calls"] == 0
    bundle = json.loads((tmp_path / "run/series.json").read_text())
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == result


def test_overdue_carry_exit_keeps_original_deadline_and_native_review_halt(tmp_path):
    old = request(tmp_path, open_end=True)
    second = old.sessions[-1]
    header = second.baseline.tape.header
    shift = timedelta(days=1)
    session = header.scope.session
    next_session = session.model_copy(
        update={
            "session_date": session.session_date + shift,
            **{
                k: getattr(session, k) + shift
                for k in (
                    "opens_at",
                    "entry_starts_at",
                    "entry_cutoff_at",
                    "protect_at",
                    "closes_at",
                )
            },
        }
    )
    next_header = TapeHeader.model_validate(
        header.model_dump()
        | {
            "session_key": str(next_session.session_date),
            "opens_at": header.opens_at + shift,
            "closes_at": header.closes_at + shift,
            "scope": header.scope.model_copy(update={"session": next_session}),
        }
    )
    source = second.baseline.tape.events[0].frame
    frames = []
    for at in (
        next_header.opens_at,
        next_header.opens_at + timedelta(seconds=1),
        next_header.closes_at,
    ):
        f = DegenFrame(
            quotes=tuple(
                q.model_copy(update={"source_at": at, "received_at": at}) for q in source.quotes
            ),
            underlyings=tuple(
                u.model_copy(update={"source_at": at, "received_at": at})
                for u in source.underlyings
            ),
        )
        frames.append((at, "MARKET", f))
    tape = record(tmp_path / "overdue.tape", next_header, frames)
    actions = (
        ScopeTapeWatchAction(
            key="overdue-advance", kind="ADVANCE", at=next_header.opens_at, play_key="first"
        ),
    )
    third = ScopeCarryComparison(
        **{
            name: getattr(second, name).model_copy(update={"tape": tape, "watch_actions": actions})
            for name in ("baseline", "shortlist", "entry", "managed")
        }
    )
    req = ScopeCarrySeries(
        sessions=(*old.sessions, third),
        gaps=(
            *old.gaps,
            ScopeCarryGap(
                starts_at=header.closes_at,
                ends_at=next_header.opens_at,
                data_cost=".03",
                host_cost=".04",
            ),
        ),
    )
    result = asyncio.run(run_scope_carry_series(req, tmp_path / "run"))
    assert not result["comparison_complete"]
    assert not result["sessions"][1]["comparison_complete"]
    bundle = json.loads((tmp_path / "run/series.json").read_text())
    for arm in "ABCD":
        gap = result["overnight_intervals"][1]["accounts"][arm]
        assert gap["ownership_status"] == "UNRESOLVED_CARRY_EXIT"
        assert gap["position"]["exit_at"] == gap["position"]["swing_carry"]["exit_at"]
        final = result["sessions"][-1]["accounts"][arm]
        held = final["closing"]["position"]
        assert held["entry_client_id"] == gap["position"]["entry_client_id"]
        assert held["exit_at"] == gap["position"]["exit_at"]
        assert final["native"]["net_after_all_costs"] is None
        assert Decimal(final["native"]["data_cost"]) == Decimal(".09")
        assert Decimal(final["native"]["host_cost"]) == Decimal(".14")
        evidence = bundle["boundaries"][-1][arm]["evidence"]
        control = evidence["execution_control"][0]
        assert control[3] == 1 and control[4] == "OPTION_EXIT_REVIEW_REQUIRED"
        orders = [json.loads(v[3]) for v in evidence["execution_orders"]]
        sells = [o for o in orders if o["side"] == "SELL"]
        assert len(sells) == 1 and sells[0]["exit_at"] == gap["position"]["exit_at"]
        assert not sells[0]["prepared_at"].startswith(next_header.session_key)
        assert gap["overnight_return"] is None
    assert verify_scope_carry_series(bundle, bundle["series_hash"])["report"] == result
