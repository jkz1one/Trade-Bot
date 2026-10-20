"""Independent native C/D replay from an explicitly enrolled common Scope tape."""

import asyncio
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.entry_reasoning import EntryReasoningPolicy
from app.options.lifecycle import OptionExecutionPolicy
from app.options.market_tape import RecordedTape
from app.options.models import Money, OptionLimits, OptionRecord
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.replay import _save
from app.options.scope_arbitration import SharedScopePolicy
from app.options.scope_execution_export import export_scope_execution
from app.options.scope_replay import MAX_REQUEST_BYTES
from app.options.scope_replay_enrollment import ScopeReplayEnrollment
from app.options.scope_replay_model import ScopeReplayModel, ScopeReplayScript
from app.options.scope_tape_watch import ScopeTapeWatchAction
from app.options.scope_trading_replay import ScopeTradingReplay, _ScopeReplay
from app.options.venue import DurableOptionVenue


class ScopeModelReplay(OptionRecord):
    version: Literal["scope-native-model-tape-replay-v1"] = "scope-native-model-tape-replay-v1"
    tape: RecordedTape
    limits: OptionLimits
    execution: OptionExecutionPolicy
    scope: SharedScopePolicy
    watch_actions: tuple[ScopeTapeWatchAction, ...] = Field(min_length=1, max_length=200)
    script: ScopeReplayScript
    judgment_limits: JudgmentLimits
    entry_policy: EntryReasoningPolicy
    position_policy: PositionReasoningPolicy | None = None
    data_cost: Money | None = Field(default=None, ge=0)
    host_cost: Money | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def enrollment(self):
        if (
            self.scope.version != "shared-scope-entry-v1"
            or self.execution.scope_arbitration != self.scope.version
            or self.execution.cost_policy is None
            or self.entry_policy.scope_selection != "scope-fixed-plan-v1"
            or self.entry_policy.max_carry_horizon_seconds is not None
            or (self.script.arm == "D") != (self.position_policy is not None)
            or (
                self.position_policy is not None
                and (
                    self.position_policy.scope_management != "scope-fixed-position-v1"
                    or self.position_policy.swing_carry is not None
                )
            )
        ):
            raise ValueError("Complete frozen C/D Scope model enrollment required")
        # Reuse the exact common tape/watch/owner validation. This model-off
        # projection is only validation; it is never persisted or used for execution.
        ScopeTradingReplay(
            tape=self.tape,
            limits=self.limits,
            execution=self.execution.model_copy(
                update={
                    "scope_arbitration": "shared-scope-selection-v1",
                    "cost_policy": None,
                }
            ),
            scope=self.scope.model_copy(update={"version": "shared-scope-selection-v1"}),
            watch_actions=self.watch_actions,
            data_cost=self.data_cost,
            host_cost=self.host_cost,
        )
        return self


class _ScopeModelReplay(_ScopeReplay):
    def __init__(self, coordinator, venue, request, clock):
        super().__init__(coordinator, venue, request, clock)
        self.scope_observations = {}
        self.fresh_reads = []

    async def observe(self, at, event=None):
        if event is not None and event.frame.scope is not None:
            self.scope_observations[event.frame.scope.play_key] = event
        await super().observe(at, event)

    async def fresh_scope(self, play_key):
        event = self.scope_observations.get(play_key)
        if event is None or event.recorded_at > self.clock[0]:
            raise ExecutionBlocked("SCOPE_DELIVERED_REPLAY_OBSERVATION_REQUIRED")
        self.fresh_reads.append(
            {
                "play_key": play_key,
                "at": self.clock[0].isoformat(),
                "sequence": event.sequence,
                "event_hash": fingerprint(event),
                "input_hash": fingerprint(event.frame.scope),
                "tape_hash": self.tape.digest,
            }
        )
        # Never rewrite a source clock or merge a newer quote into older context.
        # Native paid reapproval checks every required clock advances and the terms,
        # account revision, charged budget and original deadlines still agree.
        return event.frame.scope

    async def run(self):
        await self.observe(self.clock[0])
        try:
            while True:
                event = self.tape.events[self.index] if self.index < len(self.tape.events) else None
                pending = self.c.replay_model.pending
                timer = self.next_timer()
                at = min(
                    (
                        t
                        for t in (
                            event.recorded_at if event else None,
                            pending[0] if pending else None,
                            timer,
                        )
                        if t is not None
                    ),
                    default=None,
                )
                if at is None:
                    break
                if event is not None and event.recorded_at == at:
                    await self.observe(at, event)
                    self.index += 1
                    if event.kind == "CYCLE":
                        if self.task is None:
                            self.task = asyncio.create_task(self.c.cycle(event.frame))
                            await self.settle_task()
                        else:
                            self.skipped.append(event.cycle_key)
                elif timer == at:
                    await self.observe(at)
                more = (
                    self.index < len(self.tape.events)
                    and self.tape.events[self.index].recorded_at == at
                )
                if pending is not None and pending[0] == at and not more:
                    self.clock[0] = at
                    pending[1].set_result(None)
                    await self.task
                    self.task = None
                    # Check failures after completion as well as before suspension.
                    await self.settle_task()
                    # Settled cost and terminal application now have stable native
                    # attribution, even when protection closed the holding first.
                    self.c.engine.refresh_loss_control(now=self.clock[0])
            if self.clock[0] < self.tape.header.closes_at:
                await self.observe(self.tape.header.closes_at)
            if self.action_index != len(self.instructions):
                raise ValueError("Scope replay did not process every watch instruction")
            return {
                "skipped_cycles": self.skipped,
                "model_scripts_used": sorted(self.c.replay_model.used),
            }
        finally:
            if self.task is not None:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)


async def run_scope_model_replay(request, directory):
    request = ScopeModelReplay.model_validate(request.model_dump(warnings=False))
    if len(request.model_dump_json().encode()) > MAX_REQUEST_BYTES:
        raise ValueError("Bounded Scope model replay request required")
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute new Scope model replay directory required")
    directory.mkdir(mode=0o700)
    digest = fingerprint(request)
    enrollment = ScopeReplayEnrollment(
        tape_hash=request.tape.digest, request_hash=digest, script_hash=fingerprint(request.script)
    )
    _save(
        directory / "inputs.json",
        {"request_hash": digest, "request": request.model_dump(mode="json")},
    )
    h = request.tape.header
    clock = [h.opens_at]
    replay = None

    async def fresh_scope(play):
        if replay is None:
            raise ExecutionBlocked("SCOPE_REPLAY_SCHEDULER_REQUIRED")
        return await replay.fresh_scope(play)

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
            coordinator = DegenCoordinator(
                engine,
                h.setup,
                h.selection,
                create=True,
                clock=lambda: clock[0],
                scope_policy=request.scope,
                swing_policy=h.swing,
                scope_refresh=fresh_scope,
                scope_replay=enrollment,
                replay_model=ScopeReplayModel(request.script),
                judgment_limits=request.judgment_limits,
                entry_policy=request.entry_policy,
                position_policy=request.position_policy,
            )
            replay = _ScopeModelReplay(coordinator, venue, request, clock)
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
            report = json.loads(
                json.dumps(
                    {
                        "version": request.version,
                        "status": "COMPLETE_SCOPE_MODEL_TAPE_REPLAY",
                        "arm": request.script.arm,
                        "request_hash": digest,
                        "tape_hash": request.tape.digest,
                        "enrollment": enrollment.model_dump(mode="json"),
                        "export_hash": exported["export_hash"],
                        "watch_actions": replay.actions,
                        "fresh_reads": replay.fresh_reads,
                        "scheduler": scheduler,
                        "accounting": exported["report"],
                        "comparison_complete": False,
                        "economic_conclusion": "NOT_EVALUATED",
                        "execution_authority": False,
                        "live_enabled": False,
                    }
                )
            )
            _save(directory / "report.json", report)
            return report
    except BaseException:
        _save(
            directory / "interrupted.json",
            {
                "status": "INCOMPLETE_SCOPE_MODEL_TAPE_REPLAY",
                "request_hash": digest,
            },
        )
        raise
