"""Scope plans retain owned sizing, locked objectives and separate source estimates."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_observer import observer
from test_option_scope_owned_admission import evidence, policy, review, start
from test_option_scope_watch import owned, ready, revision

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.models import OptionAdmission, OptionProposal
from app.options.scope_contract import ScopeContractScan
from app.options.scope_management import ScopeManagementPolicy, ScopeManagementReview
from app.options.scope_watch import ScopeWatchBook

D = Decimal


def management_policy(**changes):
    return ScopeManagementPolicy.model_validate(
        {
            "responsive_loss_fraction": ".35",
            "balanced_loss_fraction": ".45",
            "convexity_loss_fraction": ".60",
            **changes,
        }
    )


def watch_policy(**changes):
    return policy().model_copy(update={"management": management_policy(**changes)})


def admitted(e, v, right="CALL", quantity=2, profile="BALANCED", *, p=None):
    book, f = start(e, v, right, watch_policy=p or watch_policy())
    fresh, c, u, now = evidence(e, f)
    ask = {1: D(2), 2: D(2), 3: D("1.5"), 4: D(1)}[quantity]
    delta = D(".50" if profile == "RESPONSIVE" else ".32") * (1 if right == "CALL" else -1)
    fresh = fresh.model_copy(
        update={
            "quote": fresh.quote.model_copy(update={"bid": ask, "ask": ask, "ask_size": quantity}),
            "metadata": fresh.metadata.model_copy(update={"delta": delta}),
        }
    )
    ready(e, v, now)
    out = review(book, fresh, c, u, now)
    assert out["record"]["admission_review"]["eligible"], out["record"]["admission_review"][
        "reasons"
    ]
    return book, out, fresh, c, u, now


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "quantity,allocation",
    [(1, (0, 1, 0, 0)), (2, (1, 0, 0, 1)), (3, (1, 1, 0, 1)), (4, (1, 1, 1, 1))],
)
@pytest.mark.parametrize("profile,fraction", [("RESPONSIVE", ".35"), ("BALANCED", ".45")])
def test_source_allocations_use_owned_quantity_and_exact_locked_targets(
    tmp_path, right, quantity, allocation, profile, fraction
):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, f, c, u, now = admitted(e, v, right, quantity, profile)
        record = out["record"]
        r = record["admission_review"]
        plan = ScopeManagementReview.model_validate(r["management"])
        assert plan.admitted_quantity == r["admission"]["quantity"] == quantity
        assert plan.source_allocation == allocation
        assert plan.geometry.model_dump(mode="json") == record["geometry"]
        assert plan.admission_hash == fingerprint(OptionAdmission.model_validate(r["admission"]))
        assert plan.contract_scan_hash == fingerprint(
            ScopeContractScan.model_validate(record["arming"]["contract_scan"])
        )
        assert plan.contract_observation.profile == profile
        assert plan.entry_premium_protection.maximum_loss_fraction == D(fraction)
        assert not plan.authority and not plan.native_execution_ready and not plan.live_enabled
        if quantity == 4:
            assert plan.target_exit_schedule is None and not plan.passed
            assert plan.reasons == ("SCOPE_THIRD_TARGET_UNSPECIFIED",)
            assert plan.source_allocation[2] == plan.source_allocation[3] == 1
        else:
            assert plan.passed and not plan.reasons
            schedule = plan.target_exit_schedule
            assert schedule.entry_quantity == quantity
            prices = [s.underlying_price for s in schedule.steps]
            expected = [
                D(record["geometry"][field])
                for field, count in zip(("target_one", "target_two"), allocation[:2], strict=True)
                if count
            ]
            assert prices == expected
            assert sum(s.quantity for s in schedule.steps) + allocation[3] == quantity
        assert (
            book.review_admission(
                "review",
                "first",
                frame=f,
                context=c,
                underlying=u,
                now=now,
                expected_revision=out["revision"] - 1,
            )
            == out
        )
        report = observer(e, now).report()
        assert report["status"] == "OK", report
        assert report["scope"]["active_watch"]["admission"]["management"] == r["management"]
        with e.journal.read() as db:
            for table in (
                "execution_orders",
                "execution_model_calls",
                "execution_option_decisions",
            ):
                assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_stricter_explicit_scope_policy_stays_distinct_from_source_estimate(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        _, out, *_ = admitted(e, v, p=watch_policy(balanced_loss_fraction=".2"))
        plan = out["record"]["admission_review"]["management"]
        assert D(plan["entry_premium_protection"]["maximum_loss_fraction"]) == D(".2")
        assert D(plan["source_estimated_premium_stop_fraction"]) == D(".45")


def test_owner_cap_is_the_final_premium_ceiling(tmp_path):
    with owned(
        tmp_path, enroll=False, execution_policy_changes={"premium_catastrophe_fraction": D(".2")}
    ) as (e, v, _):
        _, out, *_ = admitted(e, v)
        plan = out["record"]["admission_review"]["management"]
        validated = ScopeManagementReview.model_validate(plan)
        assert validated.entry_premium_protection.maximum_loss_fraction == D(".2")
        assert validated.owner_maximum_loss_fraction == e.policy.premium_catastrophe_fraction
        assert validated.source_estimated_premium_stop_fraction == D(".45")


def test_plan_restarts_stale_reads_never_refresh_or_change_owner(tmp_path, monkeypatch):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, _, _, _, now = admitted(e, v)
        before = revision(e)
        resumed = ScopeWatchBook(e, book.policy, now=now)
        assert (
            resumed.snapshot()["watches"][0]["admission_review"]
            == out["record"]["admission_review"]
        )

        def fail(*args, **kwargs):
            raise AssertionError("stored read evaluated evidence")

        monkeypatch.setattr("app.options.scope_watch.scan_scope_contract", fail)
        report = observer(e, now + timedelta(minutes=1)).report()
        assert report["status"] == "OK"
        a = report["scope"]["active_watch"]["admission"]
        assert a["time_status"] == "EXPIRED"
        assert a["management"] == out["record"]["admission_review"]["management"]
        assert revision(e) == before


def test_failed_fresh_review_cannot_retain_previous_management_plan(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, _, f, c, u, now = admitted(e, v)
        failed = review(book, f, c, u, now, key="repeat-sources")["record"]["admission_review"]
        assert not failed["eligible"] and "management" not in failed


@pytest.mark.parametrize(
    "field,value",
    [
        ("responsive_loss_fraction", ".350000000001"),
        ("balanced_loss_fraction", ".46"),
        ("convexity_loss_fraction", ".61"),
        ("balanced_loss_fraction", True),
        ("balanced_loss_fraction", 0),
    ],
)
def test_policy_cannot_enlarge_source_ceilings(field, value):
    with pytest.raises(ValidationError):
        management_policy(**{field: value})


def test_old_cohort_cannot_enable_management_and_omits_optional_field(tmp_path):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, _ = start(e, v)
        assert "management" not in book.policy.model_dump()
        with pytest.raises(ExecutionBlocked, match="FROZEN_SCOPE_WATCH_POLICY_MISMATCH"):
            ScopeWatchBook(e, watch_policy(), now=AT)


@pytest.mark.parametrize(
    "damage", ["allocation", "geometry", "owner", "admission", "convexity", "schedule", "missing"]
)
def test_observer_rejects_inconsistent_plan_without_recalculating_it(tmp_path, damage):
    with owned(tmp_path, enroll=False) as (e, v, _):
        _, out, _, _, _, now = admitted(e, v)
        record = out["record"]
        plan = record["admission_review"]["management"]
        if damage == "allocation":
            plan["source_allocation"] = [0, 1, 0, 1]
        elif damage == "geometry":
            plan["geometry"]["target_one"] = "101.6"
        elif damage == "owner":
            plan["owner_maximum_loss_fraction"] = ".6"
        elif damage == "admission":
            plan["admission_hash"] = "0" * 64
        elif damage == "convexity":
            plan["contract_observation"]["profile"] = "CONVEXITY"
        elif damage == "schedule":
            plan["target_exit_schedule"]["steps"][0]["quantity"] = 2
        else:
            record["admission_review"].pop("management")
        with e.journal.write() as db:
            db.execute(
                "UPDATE execution_option_scope_watches SET record_json=? WHERE play_key='first'",
                (json.dumps(record),),
            )
        assert observer(e, now).report()["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("version", ["scope-management-plan-v1", "scope-management-plan-v2"])
def test_management_preview_never_bypasses_native_scope_entry_guard(tmp_path, version):
    with owned(tmp_path, enroll=False) as (e, v, _):
        _, out, f, _, u, now = admitted(e, v, p=watch_policy(version=version))
        r = out["record"]["admission_review"]
        plan = ScopeManagementReview.model_validate(r["management"])
        result = e.prepare(
            "cannot-enroll",
            OptionProposal.model_validate(r["proposal"]),
            f.quote,
            u,
            now=now,
            target_exit_schedule=plan.target_exit_schedule,
            entry_premium_protection=plan.entry_premium_protection,
        )
        assert (
            result["status"] == "REJECTED"
            and result["reason"] == "SCOPE_NATIVE_EXECUTION_NOT_ENROLLED"
        )
        assert v.submit_count == 0


def test_management_review_rolls_back_with_failed_audit(tmp_path, monkeypatch):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, f = start(e, v, watch_policy=watch_policy())
        fresh, c, u, now = evidence(e, f)
        ready(e, v, now)
        before = book.snapshot()
        event = e.journal.event

        def fail(*args, **kwargs):
            event(*args, **kwargs)
            raise RuntimeError("injected management audit failure")

        monkeypatch.setattr(e.journal, "event", fail)
        with pytest.raises(RuntimeError, match="injected"):
            review(book, fresh, c, u, now)
        assert book.snapshot() == before


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("quantity", [1, 2, 3, 4])
def test_v2_retains_both_milestones_and_defers_entry_price_to_native_fills(
    tmp_path, right, quantity
):
    with owned(tmp_path, enroll=False) as (e, v, _):
        book, out, _, _, _, now = admitted(
            e, v, right, quantity, p=watch_policy(version="scope-management-plan-v2")
        )
        raw = out["record"]["admission_review"]["management"]
        review = ScopeManagementReview.model_validate(raw)
        assert review.version == review.policy.version == "scope-management-plan-v2"
        if quantity == 4:
            assert review.target_exit_schedule is None
            assert review.reasons == ("SCOPE_THIRD_TARGET_UNSPECIFIED",)
        else:
            schedule = review.target_exit_schedule
            assert schedule.version == "frozen-target-milestones-v2"
            first, second = schedule.steps
            assert first.underlying_price == review.geometry.target_one
            assert second.underlying_price == review.geometry.target_two
            assert first.quantity == review.source_allocation[0]
            assert second.quantity == review.source_allocation[1]
            assert first.tighten_underlying_to is None
            assert first.tighten_to_entry == "fill-weighted-underlying-v1"
            assert second.tighten_underlying_to == review.geometry.target_one
            schedule.check_stops(right, review.geometry.invalidation)
        assert observer(e, now).report()["scope"]["active_watch"]["admission"]["management"] == raw
        assert not review.native_execution_ready and v.submit_count == 0
        with pytest.raises(ValidationError, match="exact source allocations"):
            ScopeManagementReview.model_validate(raw | {"version": "scope-management-plan-v1"})
        with pytest.raises(ExecutionBlocked, match="FROZEN_SCOPE_WATCH_POLICY_MISMATCH"):
            ScopeWatchBook(e, watch_policy(), now=now)
        assert book.snapshot()["watches"][0]["play_key"] == "first"


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_v2_plan_survives_portable_scope_reproduction(tmp_path, right):
    from test_option_scope_replay import settings, tape
    from test_option_scope_replay_verify import snapshot

    from app.options.scope_replay import run_scope_replay
    from app.options.scope_replay_verify import verify_scope_replay

    request = settings(tape(right), watch=watch_policy(version="scope-management-plan-v2"))
    home = tmp_path / "replay"
    run_scope_replay(request, home)
    before = snapshot(home)
    result = verify_scope_replay(home, fingerprint(request))
    assert result["status"] == "VERIFIED_RESEARCH_REPLAY"
    raw = json.loads((home / "actions/007.json").read_text())["receipt"]["record"][
        "admission_review"
    ]["management"]
    plan = ScopeManagementReview.model_validate(raw)
    assert plan.target_exit_schedule.needs_entry_reference
    assert plan.target_exit_schedule.steps[1].quantity == 0
    assert not plan.native_execution_ready
    assert snapshot(home) == before
