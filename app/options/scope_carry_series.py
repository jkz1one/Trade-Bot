"""Separate combined carry series, independent owners and explicit gap accounting."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import exact, fingerprint
from app.options.models import Money, OptionRecord
from app.options.scope_carry import validate_enrollment, validate_policy
from app.options.scope_carry_replay_model import ScopeCarryScript, ScopeCarryShortlistScript
from app.options.scope_comparison import ScopeComparison
from app.options.scope_model_replay import ScopeModelReplay, _ScopeModelReplay
from app.options.scope_series import (
    MAX_BUNDLE_BYTES,
    ScopeSeries,
    _run_scope_series,
    _series_report,
)
from app.options.scope_trading_replay import (
    ScopeTradingReplay,
    _ScopeReplay,
    _validate_trading_owner,
)


class _CarryOpeningObservation:
    async def observe(self, at, event=None):
        # The old flat-session scheduler first observes an empty opening tick.
        # With a carried holding and a real same-clock receipt, that synthetic
        # absence would latch a stale-price halt before delivering the receipt.
        # Defer only this initial empty observation. Missing/later held quotes
        # still pass through ordinary native protection and its persistent halt.
        if (
            event is None
            and self.received_sequence == 0
            and at == self.tape.header.opens_at
            and self.tape.events
            and self.tape.events[0].recorded_at == at
        ):
            return
        return await super().observe(at, event)


class _ScopeCarryReplay(_CarryOpeningObservation, _ScopeReplay):
    pass


class _ScopeCarryModelReplay(_CarryOpeningObservation, _ScopeModelReplay):
    pass


class ScopeCarryTradingReplay(ScopeTradingReplay):
    version: Literal["scope-carry-deterministic-tape-v1"] = "scope-carry-deterministic-tape-v1"

    @model_validator(mode="after")
    def frozen_owner(self):
        _validate_trading_owner(self, carry=True)
        validate_enrollment(self.execution, self.scope, self.tape.header.swing)
        return self


class ScopeCarryModelReplay(ScopeModelReplay):
    version: Literal["scope-carry-model-tape-v1"] = "scope-carry-model-tape-v1"
    script: ScopeCarryScript | ScopeCarryShortlistScript

    @model_validator(mode="after")
    def enrollment(self):
        _validate_trading_owner(self, carry=True, model=True)
        if (
            self.entry_policy.scope_selection
            != ("scope-fixed-shortlist-v1" if self.script.arm == "B" else "scope-fixed-plan-v1")
            or (self.script.arm == "D") != (self.position_policy is not None)
            or self.execution.loss_control.entry_cost_attribution is not None
        ):
            raise ValueError("Complete separate combined carry model enrollment required")
        validate_policy(
            self.execution,
            self.scope,
            self.tape.header.swing,
            self.entry_policy,
            self.position_policy,
            shortlist=True,
        )
        return self


class ScopeCarryComparison(ScopeComparison):
    version: Literal["scope-carry-independent-comparison-v1"] = (
        "scope-carry-independent-comparison-v1"
    )
    baseline: ScopeCarryTradingReplay
    shortlist: ScopeCarryModelReplay
    entry: ScopeCarryModelReplay
    managed: ScopeCarryModelReplay

    def _entry_policy_exclusions(self):
        return {"scope_selection", "scope_carry_shortlist"}

    def _matched_scripts(self):
        c, d = self.entry.script, self.managed.script
        if (
            c.arm != "C"
            or d.arm != "D"
            or {v.cycle_key: v for v in c.decisions}
            != {v.cycle_key: v for v in d.decisions if v.cycle_key.startswith("degen:")}
        ):
            raise ValueError("C/D carry entries must match choices, timing, geometry and usage")


class ScopeCarryGap(OptionRecord):
    starts_at: datetime
    ends_at: datetime
    data_cost: Money | None = Field(default=None, ge=0)
    host_cost: Money | None = Field(default=None, ge=0)


class ScopeCarrySeries(ScopeSeries):
    version: Literal["scope-carry-independent-series-v1"] = "scope-carry-independent-series-v1"
    sessions: tuple[ScopeCarryComparison, ...] = Field(min_length=2, max_length=60)
    gaps: tuple[ScopeCarryGap, ...] = Field(min_length=1, max_length=59)

    @model_validator(mode="after")
    def overnight_allocations(self):
        if len(self.gaps) != len(self.sessions) - 1 or any(
            (gap.starts_at, gap.ends_at)
            != (a.baseline.tape.header.closes_at, b.baseline.tape.header.opens_at)
            for gap, a, b in zip(self.gaps, self.sessions, self.sessions[1:])
        ):
            raise ValueError("Every exact between-session interval needs explicit cost allocation")
        return self


@exact
def carry_series_report(request, boundaries):
    request = ScopeCarrySeries.model_validate(request.model_dump(warnings=False))
    report = _series_report(request, boundaries)
    gaps = []
    for index, gap in enumerate(request.gaps):
        accounts = {}
        next_header = request.sessions[index + 1].baseline.tape.header
        for arm in "ABCD":
            closing = report["sessions"][index]["accounts"][arm]["closing"]
            position = closing["position"]
            ownership_status = "NO_HELD_POSITION"
            if position is not None:
                terms = position.get("swing_carry")
                if terms is None:
                    # A failed intraday close remains owned exposure, not a new
                    # carry permission. Retain its original cutoff and native
                    # incomplete accounting rather than dropping its export.
                    ownership_status = "UNRESOLVED_INTRADAY_EXPOSURE"
                elif datetime.fromisoformat(position["exit_at"]) <= gap.starts_at:
                    ownership_status = "UNRESOLVED_CARRY_EXIT"
                else:
                    ownership_status = "ORIGINAL_SWING_CARRY"
                    future = [
                        s
                        for s in terms["sessions"]
                        if datetime.fromisoformat(s["opens_at"]) > gap.starts_at
                    ]
                    if not future or (
                        future[0]["session"],
                        datetime.fromisoformat(future[0]["opens_at"]),
                        datetime.fromisoformat(future[0]["closes_at"]),
                    ) != (next_header.session_key, next_header.opens_at, next_header.closes_at):
                        raise ValueError(
                            "A held carry requires its next original enumerated session"
                        )
            accounts[arm] = {
                "closing_ledger": closing,
                "position": position,
                "ownership_status": ownership_status,
                "coverage": "NOT_CONTINUOUSLY_OBSERVED" if position else "NO_HELD_POSITION",
                "overnight_return": None,
                "overnight_drawdown": None,
            }
        gaps.append({"allocation": gap.model_dump(mode="json"), "accounts": accounts})
    final = {arm: report["sessions"][-1]["accounts"][arm]["native"] for arm in "ABCD"}
    complete = all(a["status"] == "COMPLETE_FLAT_ACCOUNTING" for a in final.values())
    period = {
        arm: {
            "status": "COMPLETE_ARITHMETIC"
            if a["status"] == "COMPLETE_FLAT_ACCOUNTING"
            else "INCOMPLETE_ACCOUNTING",
            "net_after_all_costs": a["net_after_all_costs"],
            "model_costs": a["model_costs"],
            "execution_fees": a["execution_fees"],
            "data_cost": a["data_cost"],
            "host_cost": a["host_cost"],
            "benchmark_comparison": None,
        }
        for arm, a in final.items()
    }
    report.update(
        status="COMPLETE_CARRY_PERIOD_ACCOUNTING" if complete else "INCOMPLETE_ACCOUNTING",
        comparison_complete=complete,
        carry_period_accounting=period,
        overnight_intervals=gaps,
        net_difference_vs_a={
            arm: str(
                Decimal(period[arm]["net_after_all_costs"])
                - Decimal(period["A"]["net_after_all_costs"])
            )
            if complete
            else None
            for arm in "BCD"
        },
        net_return_difference_vs_spy={arm: None for arm in "ABCD"},
        benchmark_limitations="Session-only SPY endpoints exclude overnight gaps; no matched whole-period benchmark or overnight path is inferred",
    )
    return report


async def run_scope_carry_series(request, directory):
    request = ScopeCarrySeries.model_validate(request.model_dump(warnings=False))
    return await _run_scope_series(request, directory, carry_series_report)


def verify_scope_carry_series(bundle, expected_series_hash):
    if set(bundle) != {"request", "boundaries", "report", "series_hash"} or (
        len(json.dumps(bundle, allow_nan=False).encode()) > MAX_BUNDLE_BYTES
    ):
        raise ValueError("Bounded combined carry series envelope required")
    if (
        bundle["series_hash"] != expected_series_hash
        or fingerprint({k: v for k, v in bundle.items() if k != "series_hash"})
        != expected_series_hash
    ):
        raise ValueError("Carry series differs from independently retained hash")
    report = carry_series_report(
        ScopeCarrySeries.model_validate(bundle["request"]), bundle["boundaries"]
    )
    if report != bundle["report"]:
        raise ValueError("Carry series totals differ from native evidence")
    return {"status": "VERIFIED_NATIVE_CARRY_SERIES", "report": report}
