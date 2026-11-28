"""Deterministic shared Scope trading from a sealed tape; no model or provider calls."""

import asyncio
import json
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.lifecycle import OptionExecutionPolicy
from app.options.market_tape import RecordedTape
from app.options.models import Money, OptionLimits, OptionRecord
from app.options.replay import _ArmReplay, _save
from app.options.scope_arbitration import SharedScopePolicy
from app.options.scope_execution_export import export_scope_execution
from app.options.scope_replay import MAX_REQUEST_BYTES, _perform, _revision
from app.options.scope_tape_watch import ScopeTapeWatchAction, resolve_scope_watch_actions
from app.options.venue import DurableOptionVenue


class ScopeTradingReplay(OptionRecord):
    version: Literal["scope-deterministic-tape-replay-v1"] = "scope-deterministic-tape-replay-v1"
    tape: RecordedTape
    limits: OptionLimits
    execution: OptionExecutionPolicy
    scope: SharedScopePolicy
    watch_actions: tuple[ScopeTapeWatchAction, ...] = Field(min_length=1, max_length=200)
    data_cost: Money | None = Field(default=None, ge=0)
    host_cost: Money | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def frozen_owner(self):
        return _validate_trading_owner(self)


def _validate_trading_owner(self, *, carry=False, model=False):
    h = self.tape.header
    identities = {"population_id", "account_id"}
    if (
        h.scope is None
        or self.scope.version != ("shared-scope-entry-v1" if model else "shared-scope-selection-v1")
        or self.execution.scope_arbitration != self.scope.version
        or self.execution.scope_execution != "scope-native-v1"
        or (self.execution.cost_policy is not None) != model
        or self.scope.watch != h.scope.watch
        or self.limits.model_dump(exclude=identities) != h.limits.model_dump(exclude=identities)
        or (h.swing is not None) != ("SWING" in self.scope.family_priority)
        or (h.swing is not None and h.swing.carry is not None) != carry
        or (self.execution.swing_carry is not None) != carry
        or self.execution.loss_control is None
        or not set(self.scope.family_priority)
        <= {f.family for f in self.execution.loss_control.families}
    ):
        raise ValueError("Matching model-off shared Scope tape/owner policies required")
    actions = self.watch_actions
    if len({a.key for a in actions}) != len(actions) or any(
        a.at > b.at for a, b in pairwise(actions)
    ):
        raise ValueError("Ordered unique tape watch actions required")
    # Equal-time instructions cannot consume evidence before it is delivered.
    for a, b in pairwise(actions):
        if a.at == b.at and (a.sequence or 0) > (b.sequence or 0):
            raise ValueError("Equal-time watch references must follow receipt order")
    if any(a.at > h.closes_at for a in actions):
        raise ValueError("Watch instructions must finish within the session")
    resolve_scope_watch_actions(self.tape, actions)
    return self


class _ScopeReplay(_ArmReplay):
    def __init__(self, coordinator, venue, request, clock):
        super().__init__(coordinator, venue, request.tape, clock)
        self.instructions = request.watch_actions
        self.resolved = resolve_scope_watch_actions(request.tape, self.instructions)
        self.action_index = 0
        self.received_sequence = 0
        self.actions = []

    def next_timer(self):
        timers = [super().next_timer()]
        if self.action_index < len(self.instructions):
            at = self.instructions[self.action_index].at
            if at > self.clock[0]:
                timers.append(at)
        return min((t for t in timers if t is not None), default=None)

    async def observe(self, at, event=None):
        projected = event
        if event is not None:
            self.received_sequence = event.sequence
            item = event.frame.scope
            if item is not None:
                # The tape validates common/nested identity and the combined quote bound.
                # Project exact delivered observations for the existing fill/protection loop.
                quotes = {q.instrument.instrument_id: q for q in event.frame.quotes}
                if item.frame.quote is not None:
                    quotes[item.frame.quote.instrument.instrument_id] = item.frame.quote
                underlyings = {u.symbol: u for u in event.frame.underlyings}
                underlyings[item.underlying.symbol] = item.underlying
                projected = SimpleNamespace(
                    sequence=event.sequence,
                    frame=SimpleNamespace(
                        quotes=tuple(quotes.values()), underlyings=tuple(underlyings.values())
                    ),
                )
        await super().observe(at, projected)
        while self.action_index < len(self.instructions):
            action = self.instructions[self.action_index]
            if action.at > at or (action.sequence or 0) > self.received_sequence:
                break
            if action.at != at:
                raise ValueError("Scope watch instruction missed its original clock")
            step, binding = self.resolved[self.action_index]
            before = _revision(self.c.engine)
            try:
                receipt = _perform(self.c.scope_book, step, before)
                result = {"status": "RECORDED", "receipt": receipt}
            except ExecutionBlocked as exc:
                if _revision(self.c.engine) != before:
                    raise ValueError(
                        "Rejected Scope watch instruction changed its journal"
                    ) from exc
                result = {"status": "REJECTED", "reason": str(exc)}
            self.actions.append(
                {
                    "instruction_hash": fingerprint(action),
                    "key": action.key,
                    "binding": binding,
                    "expected_revision": before,
                    **result,
                }
            )
            self.action_index += 1

    async def settle_task(self):
        await super().settle_task()
        with self.c.engine.journal.read() as db:
            row = db.execute(
                "SELECT result_json FROM execution_option_opportunities ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        result = json.loads(row[0]) if row and row[0] else {}
        if result.get("reason") == "DEGEN_CYCLE_FAILED":
            raise ValueError("Scope native cycle failed: " + result["error_class"])

    async def run(self):
        # Process explicit timer-only instructions at session open as well.
        await self.observe(self.clock[0])
        result = await super().run()
        if self.action_index != len(self.instructions):
            raise ValueError("Scope replay did not process every watch instruction")
        return result


async def run_scope_trading_replay(request, directory):
    """Create one independent A baseline with native attempts/fills and portable accounting."""
    request = ScopeTradingReplay.model_validate(request.model_dump(warnings=False))
    if len(request.model_dump_json().encode()) > MAX_REQUEST_BYTES:
        raise ValueError("Bounded Scope trading replay request required")
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute new Scope trading replay directory required")
    directory.mkdir(mode=0o700)
    digest = fingerprint(request)
    _save(
        directory / "inputs.json",
        {"request_hash": digest, "request": request.model_dump(mode="json")},
    )
    h = request.tape.header
    clock = [h.opens_at]
    try:
        venue = DurableOptionVenue(
            directory / "venue.db", limits=request.limits, capital=request.execution.capital
        )
        with OptionExecution.open(
            directory / "options.db",
            request.limits,
            request.execution,
            venue,
            now=clock[0],
            create=True,
        ) as engine:
            if not engine.reconcile(venue.snapshot(clock[0]), now=clock[0])["reconciled"]:
                raise ValueError("Fresh Scope replay reconciliation required")
            engine.assess(None, None, now=clock[0])
            c = DegenCoordinator(
                engine,
                h.setup,
                h.selection,
                create=True,
                clock=lambda: clock[0],
                scope_policy=request.scope,
                swing_policy=h.swing,
            )
            replay = _ScopeReplay(c, venue, request, clock)
            async with asyncio.timeout(900):
                scheduler = await replay.run()
            engine.refresh_loss_control(now=clock[0])
            exported = export_scope_execution(
                engine.journal,
                now=clock[0],
                data_cost=request.data_cost,
                host_cost=request.host_cost,
            )
            _save(directory / "native.json", exported)
            report = {
                "version": request.version,
                "status": "COMPLETE_DETERMINISTIC_TAPE_REPLAY",
                "arm": "A",
                "request_hash": digest,
                "tape_hash": request.tape.digest,
                "export_hash": exported["export_hash"],
                "watch_actions": replay.actions,
                "scheduler": scheduler,
                "accounting": exported["report"],
                "comparison_complete": False,
                "economic_conclusion": "NOT_EVALUATED",
                "execution_authority": False,
                "live_enabled": False,
            }
            report = json.loads(json.dumps(report))
            _save(directory / "report.json", report)
            return report
    except BaseException:
        _save(
            directory / "interrupted.json",
            {"status": "INCOMPLETE_DETERMINISTIC_TAPE_REPLAY", "request_hash": digest},
        )
        raise
