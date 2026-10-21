"""Matched independent A/B/C/D Scope fixture accounts and portable net accounting."""

import json
from datetime import datetime
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from app.options import entry_judgment, judgment, position_judgment
from app.options.engine import fingerprint
from app.options.models import OptionRecord
from app.options.replay import _save
from app.options.scope_execution_export import MAX_BYTES, SCHEMA, verify_scope_execution_export
from app.options.scope_model_replay import ScopeModelReplay, run_scope_model_replay
from app.options.scope_replay import MAX_REQUEST_BYTES
from app.options.scope_replay_model import MatchedScopeScripts
from app.options.scope_trading_replay import ScopeTradingReplay, run_scope_trading_replay


class ScopeComparison(OptionRecord):
    version: Literal["scope-independent-comparison-v1"] = "scope-independent-comparison-v1"
    baseline: ScopeTradingReplay
    shortlist: ScopeModelReplay
    entry: ScopeModelReplay
    managed: ScopeModelReplay

    @model_validator(mode="after")
    def matched(self):
        arms = (self.baseline, self.shortlist, self.entry, self.managed)
        if tuple(r.script.arm for r in arms[1:]) != ("B", "C", "D"):
            raise ValueError("Exactly independent A/B/C/D roles required")
        MatchedScopeScripts(entry=self.entry.script, managed=self.managed.script)
        if any(
            len({getattr(r.limits, key) for r in arms}) != 4
            for key in ("population_id", "account_id")
        ):
            raise ValueError("Four distinct population and account identities required")
        first = arms[0]
        for r in arms[1:]:
            if (
                r.tape != first.tape
                or r.watch_actions != first.watch_actions
                or r.limits.model_dump(exclude={"population_id", "account_id"})
                != first.limits.model_dump(exclude={"population_id", "account_id"})
                or r.execution.model_dump(exclude={"cost_policy", "scope_arbitration"})
                != first.execution.model_dump(exclude={"cost_policy", "scope_arbitration"})
                or r.scope.model_dump(exclude={"version"})
                != first.scope.model_dump(exclude={"version"})
                or (r.data_cost, r.host_cost) != (first.data_cost, first.host_cost)
            ):
                raise ValueError(
                    "Matched tape, watches, capital, risk, fees and operating allocations required"
                )
        for r in (self.shortlist, self.managed):
            if (
                r.execution.cost_policy != self.entry.execution.cost_policy
                or r.judgment_limits != self.entry.judgment_limits
                or r.entry_policy.model_dump(exclude={"scope_selection"})
                != self.entry.entry_policy.model_dump(exclude={"scope_selection"})
            ):
                raise ValueError("Matched model costs, deadlines and entry configuration required")
        return self


def _requests(request):
    return dict(
        zip(
            "ABCD",
            (request.baseline, request.shortlist, request.entry, request.managed),
            strict=True,
        )
    )


def comparison_report(request, exports):
    """Reconstruct each independent native export; never trust supplied totals."""
    request = ScopeComparison.model_validate(request.model_dump(warnings=False))
    if set(exports) != set("ABCD"):
        raise ValueError("Four complete native export envelopes required")
    accounts = {}
    for arm, r in _requests(request).items():
        exported = exports[arm]
        verify_scope_execution_export(exported, exported["export_hash"])
        if datetime.fromisoformat(exported["as_of"]) < max(
            r.tape.header.closes_at, r.tape.events[-1].recorded_at
        ):
            raise ValueError("Comparison requires the completed tape accounting boundary")
        # Native evidence must identify the exact retained runner enrollment/owner.
        tables = {
            table: [dict(zip(SCHEMA[table].split(), row, strict=True)) for row in rows]
            for table, rows in exported["evidence"].items()
        }
        control = json.loads(tables["execution_control"][0]["config_json"])
        strategy = json.loads(tables["execution_option_strategy"][0]["policy_json"])
        if control["limits"] != r.limits.model_dump(mode="json") or control[
            "policy"
        ] != r.execution.model_dump(mode="json"):
            raise ValueError("Comparison owner configuration changed")
        if strategy["scope"] != r.scope.model_dump(mode="json"):
            raise ValueError("Comparison shared policy changed")
        if (
            strategy["setup"] != r.tape.header.setup.model_dump(mode="json")
            or strategy["selection"] != r.tape.header.selection.model_dump(mode="json")
            or strategy.get("swing")
            != (r.tape.header.swing.model_dump(mode="json") if r.tape.header.swing else None)
        ):
            raise ValueError("Comparison tape strategy changed")
        if arm != "A" and (
            strategy["scope_replay"]["request_hash"] != fingerprint(r)
            or strategy["scope_replay"]["tape_hash"] != r.tape.digest
            or strategy["scope_replay"]["script_hash"] != fingerprint(r.script)
        ):
            raise ValueError("Comparison replay enrollment changed")
        if arm != "A" and (
            strategy.get("entry_model")
            != entry_judgment.configuration(
                r.execution.cost_policy, r.judgment_limits, r.entry_policy
            ).model_dump(mode="json")
            or strategy.get("position_model")
            != (
                position_judgment.configuration(
                    r.execution.cost_policy, r.judgment_limits, r.position_policy
                ).model_dump(mode="json")
                if r.position_policy is not None
                else None
            )
            or strategy.get("model")
            != {
                "key_file": "None",
                "configuration": judgment.configuration(r.execution.cost_policy, r.judgment_limits),
            }
        ):
            raise ValueError("Comparison full model configuration changed")
        a = exported["report"]
        if (a["data_cost"], a["host_cost"]) != (
            str(r.data_cost) if r.data_cost is not None else None,
            str(r.host_cost) if r.host_cost is not None else None,
        ):
            raise ValueError("Comparison operating allocations changed")
        accounts[arm] = a
    complete = all(a["status"] == "COMPLETE_FLAT_ACCOUNTING" for a in accounts.values())
    with localcontext(Context(prec=192)):
        differences = {
            arm: str(
                Decimal(accounts[arm]["net_after_all_costs"])
                - Decimal(accounts["A"]["net_after_all_costs"])
            )
            if complete
            else None
            for arm in "BCD"
        }
    return {
        "version": request.version,
        "request_hash": fingerprint(request),
        "tape_hash": request.baseline.tape.digest,
        "status": "COMPLETE_FLAT_COMPARISON" if complete else "INCOMPLETE_ACCOUNTING",
        "accounts": accounts,
        "accounting_boundaries": {arm: exports[arm]["as_of"] for arm in "ABCD"},
        "net_difference_vs_a": differences,
        "comparison_complete": complete,
        "economic_conclusion": "INCONCLUSIVE",
        "benchmark_comparison": None,
        "execution_authority": False,
        "live_enabled": False,
    }


async def run_scope_comparison(request, directory):
    request = ScopeComparison.model_validate(request.model_dump(warnings=False))
    if len(request.model_dump_json().encode()) > 4 * MAX_REQUEST_BYTES:
        raise ValueError("Bounded Scope comparison request required")
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute new comparison directory required")
    directory.mkdir(mode=0o700)
    _save(
        directory / "inputs.json",
        {"request_hash": fingerprint(request), "request": request.model_dump(mode="json")},
    )
    exports = {}
    try:
        for arm, r in _requests(request).items():
            runner = run_scope_trading_replay if arm == "A" else run_scope_model_replay
            await runner(r, directory / arm)
            exports[arm] = json.loads((directory / arm / "native.json").read_text())
        report = comparison_report(request, exports)
        bundle = {"request": request.model_dump(mode="json"), "exports": exports, "report": report}
        bundle["comparison_hash"] = fingerprint(bundle)
        _save(directory / "comparison.json", bundle)
        _save(directory / "report.json", report)
        return report
    except BaseException:
        _save(
            directory / "interrupted.json",
            {
                "status": "INCOMPLETE_SCOPE_COMPARISON",
                "request_hash": fingerprint(request),
                "completed_arms": list(exports),
            },
        )
        raise


def verify_scope_comparison(bundle, expected_comparison_hash):
    if len(json.dumps(bundle, allow_nan=False).encode()) > 8 * MAX_BYTES or set(bundle) != {
        "request",
        "exports",
        "report",
        "comparison_hash",
    }:
        raise ValueError("Bounded comparison envelope required")
    body = {k: v for k, v in bundle.items() if k != "comparison_hash"}
    if (
        bundle["comparison_hash"] != expected_comparison_hash
        or fingerprint(body) != expected_comparison_hash
    ):
        raise ValueError("Comparison differs from independently retained bundle hash")
    request = ScopeComparison.model_validate(bundle["request"])
    report = comparison_report(request, bundle["exports"])
    if report != bundle["report"]:
        raise ValueError("Comparison totals differ from native evidence")
    return {"status": "VERIFIED_NATIVE_COMPARISON", "report": report}
