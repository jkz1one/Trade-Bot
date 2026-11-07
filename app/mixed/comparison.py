"""Portable common-tape binding and independent full-cost mixed comparison."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

from app.mixed.replay import MixedComparison, carry_boundary
from app.mixed.replay_enrollment import MixedReplayEnrollment
from app.mixed.replay_export import SCHEMA, verify_mixed_execution_export
from app.mixed.replay_model import response_for
from app.options import entry_judgment, judgment, position_judgment
from app.options.engine import exact, fingerprint
from app.options.scope_runtime import protection
from app.options.scope_series import _spy
from app.options.scope_tape_watch import _resolve

MAX_BUNDLE_BYTES = 256 * 1024 * 1024


def rows(envelope):
    return {
        name: [dict(zip(SCHEMA[name].split(), row, strict=True)) for row in values]
        for name, values in envelope["evidence"].items()
    }


def owner_binding(request, account, tables):
    h = request.sessions[0].tape.header
    control = json.loads(tables["execution_control"][0]["config_json"])
    strategy = json.loads(tables["execution_option_strategy"][0]["policy_json"])
    stocks = (
        h.stocks.model_copy(update={"paid_selection": "mixed-paid-entry-v1"})
        if account.script
        else h.stocks
    )
    expected = {
        "setup": h.setup.model_dump(mode="json"),
        "selection": h.selection.model_dump(mode="json"),
        "stocks": stocks.model_dump(mode="json"),
    }
    if h.swing is not None:
        expected["swing"] = h.swing.model_dump(mode="json")
    if account.scope is not None:
        expected["scope"] = account.scope.model_dump(mode="json")
    if account.script is not None:
        expected.update(
            replay_model=account.script.model_dump(mode="json"),
            mixed_replay=MixedReplayEnrollment(
                tape_hashes=tuple(s.tape.digest for s in request.sessions),
                request_hash=fingerprint(request),
                script_hash=fingerprint(account.script),
            ).model_dump(mode="json"),
            entry_model=entry_judgment.configuration(
                account.execution.cost_policy, account.judgment_limits, account.entry_policy
            ).model_dump(mode="json"),
            model={
                "key_file": "None",
                "configuration": judgment.configuration(
                    account.execution.cost_policy, account.judgment_limits
                ),
            },
        )
    if account.position_policy is not None:
        expected["position_model"] = position_judgment.configuration(
            account.execution.cost_policy, account.judgment_limits, account.position_policy
        ).model_dump(mode="json")
    if (
        control["limits"] != account.limits.model_dump(mode="json")
        or control["policy"] != account.execution.model_dump(mode="json")
        or strategy != expected
    ):
        raise ValueError("Mixed independent account configuration changed")


def continuity(previous, current):
    old, new = rows(previous), rows(current)
    if (
        not set(old) <= set(new)
        or new["execution_events"][: len(old["execution_events"])] != old["execution_events"]
    ):
        raise ValueError("Mixed session audit prefix changed")
    lower = datetime.fromisoformat(previous["as_of"])
    if any(
        datetime.fromisoformat(e["occurred_at"]) < lower
        for e in new["execution_events"][len(old["execution_events"]) :]
    ):
        raise ValueError("New mixed evidence predates a retained closing boundary")
    mutable = {
        "execution_control",
        "execution_orders",
        "execution_stock_orders",
        "execution_mixed_control",
        "execution_option_scope_watches",
        "execution_option_scope_watch_policy",
        "execution_option_loss_control",
        "execution_judgment_policy",
    }
    for table, values in old.items():
        if table not in mutable and new[table][: len(values)] != values:
            raise ValueError("Original mixed economic evidence changed: " + table)
    for table in ("execution_orders", "execution_stock_orders"):
        later = {r["client_id"]: r for r in new[table]}
        for row in old[table]:
            after = later.get(row["client_id"])
            if after is None or any(
                after[k] != row[k]
                for k in (
                    "client_id",
                    "source_key",
                    "fingerprint",
                    "intent_json",
                    "approval_json",
                    "order_id",
                    "attempted_at",
                )
            ):
                raise ValueError("Original native approval or attempt changed across sessions")
            if row["status"] in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"} and row != after:
                raise ValueError("Prior terminal native order changed")
    if old["execution_control"][0]["config_json"] != new["execution_control"][0][
        "config_json"
    ] or any(
        old["execution_mixed_control"][0][k] != new["execution_mixed_control"][0][k]
        for k in ("policy_json", "opened_at")
    ):
        raise ValueError("Original mixed capital or enrollment changed")


def tape_binding(request, account, tables, index):
    tapes = tuple(s.tape for s in request.sessions[: index + 1])
    events = [(t, e) for t in tapes for e in t.events]
    cycles = {e.cycle_key: e for _, e in events if e.kind == "CYCLE"}
    used = set()
    for row in tables["execution_option_opportunities"]:
        event = cycles.get(row["cycle_key"])
        if (
            event is None
            or json.loads(row["inputs_json"]) != event.frame.model_dump(mode="json")
            or datetime.fromisoformat(row["started_at"]) != event.recorded_at
        ):
            raise ValueError("Native mixed cycle differs from its original recorded input")
        data = json.loads(row["result_json"] or "{}")
        for kind, protocol in (("entry", entry_judgment), ("position", position_judgment)):
            if kind + "_request" not in data:
                continue
            if account.script is None:
                raise ValueError("Model-off A cannot retain a paid request")
            request_type = protocol.EntryRequest if kind == "entry" else protocol.PositionRequest
            call = request_type.model_validate(data[kind + "_request"])
            result = response_for(account.script, call)
            if result.model_dump(mode="json") != data.get(kind + "_result"):
                raise ValueError("Retained mixed model receipt differs from the declared script")
            used.add(call.packet.cycle_key)
            decision = next(
                (d for d in account.script.decisions if d.cycle_key == call.packet.cycle_key), None
            )
            completed = datetime.fromisoformat(data[kind + "_completed_at"])
            expected = call.packet.as_of + timedelta(
                seconds=decision.delay_seconds if decision else 0
            )
            if completed != expected:
                raise ValueError("Mixed response changed its original completion clock")
    for table in ("execution_orders", "execution_stock_orders"):
        for row in tables[table]:
            intent = json.loads(row["intent_json"])
            observation = json.loads(row["observation_json"] or "null")
            for fill in observation["fills"] if observation else ():
                at = datetime.fromisoformat(fill["occurred_at"])
                if datetime.fromisoformat(fill["quote"]["source_at"]) <= datetime.fromisoformat(
                    intent["prepared_at"]
                ):
                    raise ValueError("Mixed fill cannot reuse pre-approval market evidence")
                matching = []
                for _, event in events:
                    if event.recorded_at > at:
                        continue
                    quotes = (
                        tuple(x.quote for x in event.frame.stocks)
                        if table == "execution_stock_orders"
                        else protection(event.frame)[0]
                    )
                    if any(q.model_dump(mode="json") == fill["quote"] for q in quotes):
                        matching.append(event)
                if not matching:
                    raise ValueError("Native mixed fill lacks a delivered tape quote")
                if fill.get("underlying") is not None and not any(
                    event.recorded_at <= at
                    and any(
                        u.model_dump(mode="json") == fill["underlying"]
                        for u in protection(event.frame)[1]
                    )
                    for _, event in events
                ):
                    raise ValueError("Native option fill lacks its recorded underlying")
    return used


def watch_request(step, revision):
    value = {
        "kind": step.kind,
        "action": {"key": step.key, "expected_revision": revision},
        "now": step.at,
    }
    if step.kind == "CALL":
        return value | {"choice": step.choice, "frame": step.frame, "context": step.context}
    value["play_key"] = step.play_key
    fields = {
        "ADVANCE": ("frame",),
        "NEUTRALIZE": ("frame",),
        "OBSERVE_ARMING": ("frame", "context"),
        "OBSERVE_QUOTE": ("underlying",),
        "REVIEW_ADMISSION": ("frame", "context", "underlying"),
    }
    return value | {key: getattr(step, key) for key in fields[step.kind]}


def schedule_binding(session, schedule, tables, used):
    if (
        set(schedule) != {"skipped_cycles", "model_scripts_used", "watch_actions", "fresh_reads"}
        or sorted(used) != schedule["model_scripts_used"]
    ):
        raise ValueError("Complete native mixed scheduler evidence required")
    cycle_coverage(session, schedule, tables)
    if len(schedule["watch_actions"]) != len(session.watch_actions):
        raise ValueError("Mixed watch action coverage changed")
    native = {r["action_key"]: r for r in tables.get("execution_option_scope_watch_actions", [])}
    for action, receipt in zip(session.watch_actions, schedule["watch_actions"], strict=True):
        step, binding = _resolve(session.tape, action)
        if (
            receipt["key"] != action.key
            or receipt["instruction_hash"] != fingerprint(action)
            or receipt["binding"] != binding
        ):
            raise ValueError("Mixed watch instruction differs from original tape evidence")
        if receipt["status"] == "RECORDED":
            row = native.get(action.key)
            if (
                row is None
                or json.loads(row["result_json"]) != receipt["receipt"]
                or row["request_hash"]
                != fingerprint(watch_request(step, receipt["expected_revision"]))
            ):
                raise ValueError("Mixed watch instruction lacks its exact native receipt")
        elif receipt["status"] != "REJECTED" or action.key in native:
            raise ValueError("Mixed watch rejection invented native authority")
    for read in schedule["fresh_reads"]:
        event = next(
            (
                e
                for e in session.tape.available(datetime.fromisoformat(read["at"]))
                if e.sequence == read["sequence"]
            ),
            None,
        )
        if (
            event is None
            or read["tape_hash"] != session.tape.digest
            or read["event_hash"] != fingerprint(event)
        ):
            raise ValueError("Mixed paid refresh lacks a delivered original observation")
        allowed = (
            [fingerprint(x.quote) for x in event.frame.stocks]
            if read["asset"] == "STOCK"
            else [fingerprint(event.frame.scope)]
            if read["asset"] == "SCOPE" and event.frame.scope is not None
            else []
        )
        if read["input_hash"] not in allowed:
            raise ValueError("Mixed paid refresh changed its complete original source")


def cycle_coverage(session, schedule, tables):
    """Every original cycle was attempted or overlapped a retained paid response."""
    cycles = {e.cycle_key: e for e in session.tape.events if e.kind == "CYCLE"}
    attempted, intervals = set(), []
    for row in tables["execution_option_opportunities"]:
        if row["cycle_key"] not in cycles:
            continue
        if row["cycle_key"] in attempted or row["status"] != "COMPLETE" or not row["result_json"]:
            raise ValueError("Complete unique native mixed cycle receipt required")
        attempted.add(row["cycle_key"])
        data = json.loads(row["result_json"])
        for kind in ("entry", "position"):
            if kind + "_request" in data:
                intervals.append(
                    (
                        datetime.fromisoformat(data[kind + "_request"]["packet"]["as_of"]),
                        datetime.fromisoformat(data[kind + "_completed_at"]),
                    )
                )
    missing = [key for key in cycles if key not in attempted]
    if schedule["skipped_cycles"] != missing or any(
        not any(start < cycles[key].recorded_at <= end for start, end in intervals)
        for key in missing
    ):
        raise ValueError("Every mixed cycle requires a native attempt or original paid overlap")


@exact
def comparison_report(request, boundaries, schedules):
    request = MixedComparison.model_validate(request.model_dump(warnings=False))
    if len(boundaries) != len(request.sessions) or len(schedules) != len(request.sessions):
        raise ValueError("All declared mixed closing boundaries required")
    reports, previous, gaps = [], {}, []
    for index, session in enumerate(request.sessions):
        if set(boundaries[index]) != set("ABCD") or set(schedules[index]) != set("ABCD"):
            raise ValueError("Four independent native closing accounts required")
        if index:
            gaps.append(
                {
                    "starts_at": request.sessions[index - 1].tape.header.closes_at.isoformat(),
                    "ends_at": session.tape.header.opens_at.isoformat(),
                    "cost_allocation": "Original daily calendar allocations remain in cumulative native costs",
                    "accounts": {
                        arm: carry_boundary(previous[arm], session.tape.header) for arm in "ABCD"
                    },
                }
            )
        accounts = {}
        for account in request.accounts:
            envelope = boundaries[index][account.arm]
            actual = verify_mixed_execution_export(envelope, envelope["export_hash"])
            at = datetime.fromisoformat(envelope["as_of"])
            minimum = max(
                session.tape.header.closes_at,
                session.tape.events[-1].recorded_at
                if session.tape.events
                else session.tape.header.closes_at,
            )
            if not minimum <= at <= session.tape.header.closes_at + timedelta(seconds=600):
                raise ValueError("Complete original mixed session accounting boundary required")
            tables = rows(envelope)
            owner_binding(request, account, tables)
            used = tape_binding(request, account, tables, index)
            schedule_binding(session, schedules[index][account.arm], tables, used)
            expected = {
                s.receipt.receipt_id: s.receipt.model_dump(mode="json")
                for s in request.settlements
                if s.arm == account.arm and s.receipt.occurred_at <= at
            }
            actual_funds = {
                r["receipt_id"]: json.loads(r["payload"])
                for r in tables["execution_option_receipts"]
            }
            if actual_funds != expected:
                raise ValueError("Mixed settlement differs from the original account declaration")
            earlier = previous.get(account.arm)
            if earlier is not None:
                continuity(earlier, envelope)
            before = earlier["report"]["net_after_all_costs"] if earlier else "0"
            net = actual["net_after_all_costs"]
            accounts[account.arm] = {
                "account_id": account.limits.account_id,
                "population_id": account.limits.population_id,
                "export_hash": envelope["export_hash"],
                "as_of": envelope["as_of"],
                "accounting": actual,
                "session_net_after_all_costs": str(Decimal(net) - Decimal(before))
                if net is not None and before is not None
                else None,
            }
            previous[account.arm] = envelope
        spy = _spy(session.tape)
        reports.append(
            {
                "session_key": session.tape.header.session_key,
                "tape_hash": session.tape.digest,
                "accounts": accounts,
                "spy_session_price_return": str(spy) if spy is not None else None,
            }
        )
    totals = {arm: previous[arm]["report"]["net_after_all_costs"] for arm in "ABCD"}
    complete = all(value is not None for value in totals.values())
    spy_complete = all(r["spy_session_price_return"] is not None for r in reports)
    growth = Decimal(1)
    if spy_complete:
        for row in reports:
            growth *= 1 + Decimal(row["spy_session_price_return"])
    return {
        "version": request.version,
        "request_hash": fingerprint(request),
        "sessions": reports,
        "overnight_intervals": gaps,
        "status": "COMPLETE_FLAT_COMPARISON" if complete else "INCOMPLETE_ACCOUNTING",
        "comparison_complete": complete,
        "cumulative_net_after_all_costs": totals,
        "net_difference_vs_a": {
            arm: str(Decimal(totals[arm]) - Decimal(totals["A"])) if complete else None
            for arm in "BCD"
        },
        "cash_price_return": "0",
        "spy_session_compounded_price_return": str(growth - 1) if spy_complete else None,
        "net_return_difference_vs_spy": {
            arm: str(Decimal(totals[arm]) / request.accounts[0].execution.capital - (growth - 1))
            if complete and spy_complete
            else None
            for arm in "ABCD"
        },
        "benchmark_limitations": "SPY session midpoint price return; excludes overnight gaps, dividends and benchmark costs",
        "economic_conclusion": "INCONCLUSIVE",
        "execution_authority": False,
        "live_enabled": False,
    }


def verify_mixed_comparison(bundle, expected_hash):
    if (
        len(json.dumps(bundle, allow_nan=False).encode()) > MAX_BUNDLE_BYTES
        or set(bundle) != {"version", "request", "boundaries", "schedules", "report", "bundle_hash"}
        or bundle["version"] != "mixed-comparison-bundle-v1"
    ):
        raise ValueError("Bounded complete mixed comparison bundle required")
    if (
        bundle["bundle_hash"] != expected_hash
        or fingerprint({k: v for k, v in bundle.items() if k != "bundle_hash"}) != expected_hash
    ):
        raise ValueError("Mixed comparison differs from the independently retained hash")
    request = MixedComparison.model_validate(bundle["request"])
    report = comparison_report(request, bundle["boundaries"], bundle["schedules"])
    if report != bundle["report"]:
        raise ValueError("Mixed comparison report differs from reconstructed evidence")
    return report
