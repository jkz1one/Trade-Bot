"""Frozen multi-session Scope accounts, closing evidence and independent comparison."""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, exact, fingerprint
from app.options.evaluation import _benchmark
from app.options.evaluation_models import BenchmarkSession
from app.options.lifecycle import OptionLedger
from app.options.market_tape import validate_tape_series
from app.options.models import OptionRecord
from app.options.replay import ScriptedSettlement, _capture_boundary, _save
from app.options.scope_comparison import ScopeComparison, _account_report, _requests
from app.options.scope_execution_export import export_scope_execution
from app.options.scope_model_replay import _ScopeModelReplay
from app.options.scope_replay_enrollment import ScopeSeriesEnrollment
from app.options.scope_trading_replay import _ScopeReplay
from app.options.venue import DurableOptionVenue

MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = 256 * 1024 * 1024


class ScopeSeries(OptionRecord):
    version: Literal["scope-independent-series-v1"] = "scope-independent-series-v1"
    sessions: tuple[ScopeComparison, ...] = Field(min_length=2, max_length=60)
    settlements: tuple[ScriptedSettlement, ...] = Field(default=(), max_length=180)

    @model_validator(mode="after")
    def continuous(self):
        tapes = validate_tape_series(s.baseline.tape for s in self.sessions)
        first = tapes[0].header
        if any(a.header.closes_at >= b.header.opens_at for a, b in pairwise(tapes)):
            raise ValueError("Strictly ordered distinct Scope sessions required")
        actions = [a for s in self.sessions for a in s.baseline.watch_actions]
        if len({a.key for a in actions}) != len(actions):
            raise ValueError("Watch action identities cannot be reused across sessions")
        for s, tape in zip(self.sessions, tapes, strict=True):
            h = tape.header
            if (
                any(
                    getattr(h, k) != getattr(first, k)
                    for k in (
                        "experiment_id",
                        "declared_at",
                        "limits",
                        "setup",
                        "selection",
                        "swing",
                    )
                )
                or h.scope.watch != first.scope.watch
            ):
                raise ValueError("Frozen series market/source/strategy declaration required")
            for arm, r in _requests(s).items():
                original = _requests(self.sessions[0])[arm]
                if r.model_dump(exclude={"tape", "watch_actions", "data_cost", "host_cost"}) != (
                    original.model_dump(exclude={"tape", "watch_actions", "data_cost", "host_cost"})
                ):
                    raise ValueError(
                        "One frozen owner and complete model script across sessions required"
                    )
        keys = {e.cycle_key.split(":")[1] for t in tapes for e in t.events if e.kind == "CYCLE"}
        for r in list(_requests(self.sessions[0]).values())[1:]:
            if any(d.cycle_key.split(":")[1] not in keys for d in r.script.decisions):
                raise ValueError("Script decisions must name declared tape cycle slots")
        if len({(r.arm, r.receipt.receipt_id) for r in self.settlements}) != len(self.settlements):
            raise ValueError("Unique per-account settlement identities required")
        if any(
            not any(
                a.header.closes_at < r.receipt.occurred_at <= b.header.opens_at
                for a, b in pairwise(tapes)
            )
            for r in self.settlements
        ):
            raise ValueError("Explicit between-session funds settlements required")
        if len(self.model_dump_json().encode()) > MAX_REQUEST_BYTES:
            raise ValueError("Scope series request capacity exceeded")
        return self


def _enrollment(request, arm):
    if arm == "A":
        return None
    r = _requests(request.sessions[0])[arm]
    if request.version == "scope-carry-independent-series-v1":
        from app.options.scope_replay_enrollment import ScopeCarrySeriesEnrollment

        enrollment_type = ScopeCarrySeriesEnrollment
    else:
        enrollment_type = ScopeSeriesEnrollment
    return enrollment_type(
        tape_hashes=tuple(s.baseline.tape.digest for s in request.sessions),
        request_hash=fingerprint(request),
        script_hash=fingerprint(r.script),
    )


@exact
def _session_costs(request, index):
    session = request.sessions[index].baseline
    costs = session.data_cost, session.host_cost
    if request.version == "scope-carry-independent-series-v1" and index:
        gap = request.gaps[index - 1]
        return tuple(
            None if a is None or b is None else a + b
            for a, b in zip(costs, (gap.data_cost, gap.host_cost), strict=True)
        )
    return costs


@exact
def _allocations(request, index):
    # A missing earlier allocation stays missing; it cannot disappear on a later day.
    return tuple(
        None if any(v is None for v in values) else sum(values, Decimal(0))
        for values in ([_session_costs(request, j)[k] for j in range(index + 1)] for k in (0, 1))
    )


def _continuity(previous, current):
    """Immutable evidence remains exact; live control/holding state may progress."""
    old, new = previous["evidence"], current["evidence"]
    if not set(old) <= set(new):
        raise ValueError("Prior native tables disappeared")
    if new["execution_events"][: len(old["execution_events"])] != old["execution_events"]:
        raise ValueError("Prior native audit prefix changed")
    lower = datetime.fromisoformat(previous["as_of"])
    if any(
        datetime.fromisoformat(e[1]) < lower
        for e in new["execution_events"][len(old["execution_events"]) :]
    ):
        raise ValueError("New audit evidence predates the retained closing boundary")
    mutable = {
        "execution_control",
        "execution_orders",
        "execution_option_scope_watches",
        "execution_option_scope_watch_policy",
        "execution_option_loss_control",
        "execution_judgment_policy",
    }
    for table, rows in old.items():
        if table not in mutable and new[table][: len(rows)] != rows:
            raise ValueError("Prior native economic evidence changed: " + table)
    if old["execution_control"][0][1] != new["execution_control"][0][1]:
        raise ValueError("Prior account configuration changed")
    orders = {r[0]: r for r in new["execution_orders"]}
    for row in old["execution_orders"]:
        later = orders.get(row[0])
        # Prepared authority/identity is immutable, including original expiry/protection.
        if later is None or later[:5] != row[:5] or later[7:9] != row[7:9]:
            raise ValueError("Prior native order authority changed")
        if row[5] in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"} and later != row:
            raise ValueError("Prior terminal order changed")
    if (
        new["execution_option_scope_watch_policy"][0][1]
        != (old["execution_option_scope_watch_policy"][0][1])
    ):
        raise ValueError("Prior watch configuration changed")
    watches = {r[0]: r for r in new["execution_option_scope_watches"]}
    if any(
        r[0] not in watches or watches[r[0]][1] != r[1]
        for r in old["execution_option_scope_watches"]
    ):
        raise ValueError("Prior Scope watch identity disappeared")


def _spy(tape):
    h = tape.header
    quotes = [q for e in tape.events for q in e.frame.underlyings if q.symbol == "SPY"]
    starts = [q for q in quotes if 0 <= (q.source_at - h.opens_at).total_seconds() <= 5]
    ends = [q for q in quotes if 0 <= (h.closes_at - q.source_at).total_seconds() <= 5]
    if not starts or not ends:
        return None
    return _benchmark(
        BenchmarkSession(
            session_key=h.session_key,
            start=min(starts, key=lambda q: q.source_at),
            end=max(ends, key=lambda q: q.source_at),
        ),
        h,
        h.limits.underlying_source,
    )


@exact
def series_report(request, boundaries):
    request = ScopeSeries.model_validate(request.model_dump(warnings=False))
    return _series_report(request, boundaries)


@exact
def _series_report(request, boundaries):
    if len(boundaries) != len(request.sessions):
        raise ValueError("Every declared closing boundary required")
    rows, previous = [], {}
    for index, (session, exports) in enumerate(zip(request.sessions, boundaries, strict=True)):
        if set(exports) != set("ABCD"):
            raise ValueError("Four independent closing exports required")
        h = session.baseline.tape.header
        accounts, receipts = {}, {}
        for arm, r in _requests(session).items():
            envelope = exports[arm]
            at = datetime.fromisoformat(envelope["as_of"])
            if index + 1 < len(request.sessions) and at >= (
                request.sessions[index + 1].baseline.tape.header.opens_at
            ):
                raise ValueError("Closing evidence overlaps the next session")
            enrollment = _enrollment(request, arm)
            account = _account_report(
                arm,
                r,
                envelope,
                enrollment=enrollment.model_dump(mode="json") if enrollment else None,
                allocations=_allocations(request, index),
            )
            earlier = previous.get(arm)
            if earlier:
                _continuity(earlier, envelope)
            # A later export cannot silently discover an old call/order/fill and
            # reassign its economics to the next day. Corrections need a new protocol.
            evidence = envelope["evidence"]
            old = earlier["evidence"] if earlier else {}
            for table, read_time in (
                ("execution_orders", lambda v: json.loads(v[3])["prepared_at"]),
                ("execution_model_calls", lambda v: v[2]),
                ("execution_option_opportunities", lambda v: v[2]),
                ("execution_fills", lambda v: json.loads(v[2])["occurred_at"]),
            ):
                prior_ids = {v[0] for v in old.get(table, [])}
                if any(
                    not h.opens_at <= datetime.fromisoformat(read_time(v)) <= at
                    for v in evidence[table]
                    if v[0] not in prior_ids
                ):
                    raise ValueError("New economic evidence predates its declared session")
            initial = (
                earlier["report"]["ledger"]
                if earlier
                else OptionLedger(
                    cash=r.execution.capital, high_watermark=r.execution.capital
                ).model_dump(mode="json")
            )
            old_cost = (
                Decimal(earlier["report"]["model_costs"]["known_cost"]) if earlier else Decimal(0)
            )
            known_cost = Decimal(account["model_costs"]["known_cost"]) - old_cost
            # The cumulative native exporter retains unknown prior costs/exposure.
            complete = account["status"] == "COMPLETE_FLAT_ACCOUNTING" and (
                earlier is None or earlier["report"]["status"] == "COMPLETE_FLAT_ACCOUNTING"
            )
            data_cost, host_cost = _session_costs(request, index)
            net = (
                (
                    Decimal(account["ledger"]["cash"])
                    - Decimal(initial["cash"])
                    - known_cost
                    - data_cost
                    - host_cost
                )
                if complete
                else None
            )
            accounts[arm] = {
                "opening": initial,
                "closing": account["ledger"],
                "native": account,
                "model_cost_increment": str(known_cost),
                "execution_fee_increment": str(
                    Decimal(account["execution_fees"])
                    - (Decimal(earlier["report"]["execution_fees"]) if earlier else Decimal(0))
                ),
                "data_cost": str(data_cost) if data_cost is not None else None,
                "host_cost": str(host_cost) if host_cost is not None else None,
                "net_after_all_costs": str(net) if net is not None else None,
                "complete": complete,
            }
            receipts[arm] = {
                "export_hash": envelope["export_hash"],
                "previous_export_hash": earlier["export_hash"] if earlier else None,
                "as_of": envelope["as_of"],
            }
            # Funds credits must be the exact predeclared receipts, never inferred T+1.
            funds = [json.loads(v[1]) for v in envelope["evidence"]["execution_option_receipts"]]
            expected = [
                s.receipt.model_dump(mode="json")
                for s in request.settlements
                if s.arm == arm and s.receipt.occurred_at <= at
            ]
            if {v["receipt_id"]: v for v in funds} != {v["receipt_id"]: v for v in expected}:
                raise ValueError("Native settlement differs from frozen series declaration")
            previous[arm] = envelope
        complete = all(v["complete"] for v in accounts.values())
        spy = _spy(session.baseline.tape)
        rows.append(
            {
                "session_key": h.session_key,
                "tape_hash": session.baseline.tape.digest,
                "accounts": accounts,
                "boundaries": receipts,
                "comparison_complete": complete,
                "net_difference_vs_a": {
                    arm: str(
                        Decimal(accounts[arm]["net_after_all_costs"])
                        - Decimal(accounts["A"]["net_after_all_costs"])
                    )
                    if complete
                    else None
                    for arm in "BCD"
                },
                "spy_session_price_return": str(spy) if spy is not None else None,
            }
        )
    complete = all(r["comparison_complete"] for r in rows)
    totals = {arm: previous[arm]["report"]["net_after_all_costs"] for arm in "ABCD"}
    spy_complete = all(r["spy_session_price_return"] is not None for r in rows)
    spy_growth = Decimal(1)
    if spy_complete:
        for row in rows:
            spy_growth *= 1 + Decimal(row["spy_session_price_return"])
    report = {
        "version": request.version,
        "request_hash": fingerprint(request),
        "sessions": rows,
        "status": "COMPLETE_FLAT_SERIES" if complete else "INCOMPLETE_ACCOUNTING",
        "comparison_complete": complete,
        "cumulative_net_after_all_costs": totals,
        "net_difference_vs_a": {
            arm: str(Decimal(totals[arm]) - Decimal(totals["A"])) if complete else None
            for arm in "BCD"
        },
        "spy_session_compounded_price_return": str(spy_growth - 1) if spy_complete else None,
        "net_return_difference_vs_spy": {
            arm: str(
                Decimal(totals[arm]) / request.sessions[0].baseline.execution.capital
                - (spy_growth - 1)
            )
            if complete and spy_complete
            else None
            for arm in "ABCD"
        },
        "cash_price_return": "0",
        "economic_conclusion": "INCONCLUSIVE",
        "benchmark_limitations": "SPY session midpoint price return; excludes overnight gaps, dividends and benchmark costs",
        "execution_authority": False,
        "live_enabled": False,
    }
    # Native attribution may use tuples internally. Public results and retained
    # portable evidence must have the same JSON representation and comparison.
    return json.loads(json.dumps(report))


async def run_scope_series(request, directory):
    """Create once per arm; never resume, reset capital or change a frozen strategy."""
    request = ScopeSeries.model_validate(request.model_dump(warnings=False))
    return await _run_scope_series(request, directory, series_report)


async def _run_scope_series(request, directory, report_for):
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute new Scope series directory required")
    directory.mkdir(mode=0o700)
    _save(
        directory / "inputs.json",
        {"request": request.model_dump(mode="json"), "request_hash": fingerprint(request)},
    )
    boundaries = [{} for _ in request.sessions]
    retained_bytes = len(request.model_dump_json().encode())
    try:
        for arm, original in _requests(request.sessions[0]).items():
            home = directory / arm
            home.mkdir(mode=0o700)
            (home / "sessions").mkdir(mode=0o700)
            h = original.tape.header
            clock, active = [h.opens_at], [None]

            async def fresh_scope(play, active=active):
                if active[0] is None:
                    raise ExecutionBlocked("SCOPE_REPLAY_SCHEDULER_REQUIRED")
                return await active[0].fresh_scope(play)

            venue = DurableOptionVenue(
                home / "venue.db", limits=original.limits, capital=original.execution.capital
            )
            with OptionExecution.open(
                home / "options.db",
                original.limits,
                original.execution,
                venue,
                now=clock[0],
                create=True,
            ) as engine:
                if not engine.reconcile(venue.snapshot(clock[0]), now=clock[0])["reconciled"]:
                    raise ValueError("Fresh Scope series reconciliation required")
                engine.assess(None, None, now=clock[0])
                from app.options.scope_replay_enrollment import script_types

                if arm == "A":
                    model = None
                else:
                    full, shortlist = script_types(_enrollment(request, arm))
                    model = (shortlist if arm == "B" else full)(original.script)
                c = DegenCoordinator(
                    engine,
                    h.setup,
                    h.selection,
                    create=True,
                    clock=lambda clock=clock: clock[0],
                    scope_policy=original.scope,
                    swing_policy=h.swing,
                    scope_refresh=fresh_scope if model else None,
                    scope_replay=_enrollment(request, arm),
                    replay_model=model,
                    judgment_limits=original.judgment_limits if model else None,
                    entry_policy=original.entry_policy if model else None,
                    position_policy=original.position_policy if model else None,
                )
                for index, session in enumerate(request.sessions):
                    r = _requests(session)[arm]
                    h = r.tape.header
                    if index:
                        lower = request.sessions[index - 1].baseline.tape.header.closes_at
                        for s in sorted(
                            (
                                s
                                for s in request.settlements
                                if s.arm == arm and lower < s.receipt.occurred_at <= h.opens_at
                            ),
                            key=lambda s: (s.receipt.occurred_at, s.receipt.sequence),
                        ):
                            if s.receipt.occurred_at < clock[0]:
                                raise ValueError("Settlement precedes retained boundary")
                            clock[0] = s.receipt.occurred_at
                            venue.record_receipt(s.receipt)
                            if not engine.reconcile(venue.snapshot(clock[0]), now=clock[0])[
                                "reconciled"
                            ]:
                                raise ValueError("Series settlement reconciliation required")
                        if clock[0] > h.opens_at:
                            raise ValueError("Prior replay overlaps the next session")
                        clock[0] = h.opens_at
                    c._replay_quotes, c._replay_underlyings = {}, {}
                    c._position_quotes, c._position_underlyings = (), ()
                    if request.version == "scope-carry-independent-series-v1":
                        from app.options.scope_carry_series import (
                            _ScopeCarryModelReplay,
                            _ScopeCarryReplay,
                        )

                        replay_type = _ScopeCarryModelReplay if model else _ScopeCarryReplay
                    else:
                        replay_type = _ScopeModelReplay if model else _ScopeReplay
                    active[0] = replay_type(c, venue, r, clock)
                    async with asyncio.timeout(900):
                        scheduler = await active[0].run()
                    engine.refresh_loss_control(now=clock[0])
                    _capture_boundary(engine.journal, home / "sessions" / (h.session_key + ".db"))
                    data, host = _allocations(request, index)
                    exported = export_scope_execution(
                        engine.journal, now=clock[0], data_cost=data, host_cost=host
                    )
                    _save(
                        home / "sessions" / (h.session_key + ".json"),
                        {
                            "export": exported,
                            "scheduler": scheduler,
                            "watch_actions": active[0].actions,
                            "fresh_reads": active[0].fresh_reads if model else [],
                        },
                    )
                    retained_bytes += len(json.dumps(exported).encode())
                    if retained_bytes > MAX_BUNDLE_BYTES:
                        raise ValueError("Scope series retained evidence capacity exceeded")
                    boundaries[index][arm] = exported
                    active[0] = None
        report = report_for(request, boundaries)
        bundle = {
            "request": request.model_dump(mode="json"),
            "boundaries": boundaries,
            "report": report,
        }
        bundle["series_hash"] = fingerprint(bundle)
        if len(json.dumps(bundle).encode()) > MAX_BUNDLE_BYTES:
            raise ValueError("Scope series export capacity exceeded")
        _save(directory / "series.json", bundle)
        _save(directory / "report.json", report)
        return report
    except BaseException:
        _save(
            directory / "interrupted.json",
            {
                "status": "INCOMPLETE_SCOPE_SERIES",
                "request_hash": fingerprint(request),
                "completed_boundaries": [sorted(b) for b in boundaries],
            },
        )
        raise


def verify_scope_series(bundle, expected_series_hash):
    if set(bundle) != {"request", "boundaries", "report", "series_hash"} or (
        len(json.dumps(bundle, allow_nan=False).encode()) > MAX_BUNDLE_BYTES
    ):
        raise ValueError("Bounded Scope series envelope required")
    if (
        bundle["series_hash"] != expected_series_hash
        or fingerprint({k: v for k, v in bundle.items() if k != "series_hash"})
        != expected_series_hash
    ):
        raise ValueError("Series differs from independently retained hash")
    report = series_report(ScopeSeries.model_validate(bundle["request"]), bundle["boundaries"])
    if report != bundle["report"]:
        raise ValueError("Series totals differ from native evidence")
    return {"status": "VERIFIED_NATIVE_SERIES", "report": report}
