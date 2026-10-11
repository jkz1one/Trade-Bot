"""Create-only first-session A/B/C replay through native isolated PAPER owners."""

import asyncio
import json
import os
from contextlib import ExitStack
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, localcontext
from pathlib import Path

from pydantic import Field

from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution
from app.options.entry_reasoning import EntryReasoningPolicy
from app.options.evaluation_export import export_comparison, strategy_hash
from app.options.evaluation_models import EvaluationManifest
from app.options.governor import _fresh, _tick_price
from app.options.lifecycle import TERMINAL, OptionIntent
from app.options.market_tape import RecordedTape
from app.options.models import Money, OptionRecord
from app.options.replay_model import ReplayModel, ReplayScript
from app.options.venue import DurableOptionVenue


class ReplaySettings(OptionRecord):
    manifest: EvaluationManifest
    narrow: ReplayScript
    broad: ReplayScript
    judgment_limits: JudgmentLimits
    entry_policy: EntryReasoningPolicy
    data_cost_per_arm: Money | None = Field(default=None, ge=0)
    host_cost_per_arm: Money | None = Field(default=None, ge=0)


def _save(path, value):
    raw = json.dumps(value, sort_keys=True).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fill_quantity(intent, order, snapshot, quote, at, limits):
    """Conservative executable size; native venue independently validates every fill."""
    if (
        quote.instrument != intent.instrument
        or not intent.prepared_at < quote.source_at <= quote.received_at <= at
        or not order.updated_at <= at < intent.order_expires_at
        or not _fresh(
            quote.source_at,
            quote.received_at,
            at,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
        or quote.source != limits.option_source
        or quote.entitlement != "REALTIME"
        or not quote.complete
        or quote.bid is None
        or quote.ask is None
        or quote.bid <= 0
        or quote.bid > quote.ask
    ):
        return 0
    buy = intent.side == "BUY"
    raw, size = (quote.ask, quote.ask_size) if buy else (quote.bid, quote.bid_size)
    with localcontext(Context(prec=192)):
        price = _tick_price(
            raw * (1 + (1 if buy else -1) * limits.slippage_bps / 10000),
            intent.instrument.contract,
            ROUND_CEILING if buy else ROUND_FLOOR,
        )
    if (
        price <= 0
        or (buy and price > intent.limit_price)
        or (not buy and price < intent.limit_price)
    ):
        return 0
    consumed = sum(
        f.quantity
        for o in snapshot.orders
        if o.side == intent.side
        for f in o.fills
        if f.quote == quote
    )
    return max(0, min(size - consumed, order.quantity - order.filled_quantity))


class _ArmReplay:
    def __init__(self, coordinator, venue, tape, clock):
        self.c, self.venue, self.tape, self.clock = coordinator, venue, tape, clock
        self.quotes, self.underlyings = {}, {}
        self.index = 0
        self.task = None
        self.skipped = []

    def intents(self):
        with self.c.engine.journal.read() as db:
            return {
                r[0]: OptionIntent.model_validate_json(r[1])
                for r in db.execute("SELECT client_id,intent_json FROM execution_orders")
            }

    def next_timer(self):
        now = self.clock[0]
        snapshot = self.venue.snapshot(now)
        intents = self.intents()
        times = [
            intents[o.client_id].order_expires_at
            for o in snapshot.orders
            if o.status not in TERMINAL
        ]
        if snapshot.position:
            times.append(intents[snapshot.position.entry_client_id].exit_at)
        return min((t for t in times if now < t <= self.tape.header.closes_at), default=None)

    async def observe(self, at, event=None):
        self.clock[0] = at
        if event is not None:
            self.quotes.update((q.instrument.instrument_id, q) for q in event.frame.quotes)
            self.underlyings.update((q.symbol, q) for q in event.frame.underlyings)
            self.c._replay_quotes = dict(self.quotes)
            self.c._replay_underlyings = dict(self.underlyings)
        intents = self.intents()
        snapshot = self.venue.snapshot(at)
        for order in snapshot.orders:
            if order.status in TERMINAL:
                continue
            intent = intents[order.client_id]
            if at >= intent.order_expires_at:
                self.venue.record_terminal(order.client_id, "EXPIRED", at)
                continue
            # Only newly delivered quotes can fill. Cached quotes never get replayed.
            for quote in event.frame.quotes if event is not None else ():
                snapshot = self.venue.snapshot(at)
                current = next(o for o in snapshot.orders if o.client_id == order.client_id)
                count = fill_quantity(intent, current, snapshot, quote, at, self.c.engine.limits)
                if count:
                    self.venue.fill(
                        intent,
                        count,
                        quote,
                        at,
                        fill_id=f"replay-{event.sequence}-{order.client_id}",
                    )
        snapshot = self.venue.snapshot(at)
        if not self.c.engine.reconcile(snapshot, now=at)["reconciled"]:
            raise ValueError("Replay fixture failed authoritative reconciliation")
        if snapshot.position:
            held = intents[snapshot.position.entry_client_id].instrument
            q, u = (
                self.quotes.get(held.instrument_id),
                self.underlyings.get(held.contract.underlying),
            )
            await self.c.supervise((q,) if q is not None else (), (u,) if u is not None else ())

        else:
            self.c.engine.assess(None, None, now=at)

    async def settle_task(self):
        """Wait for native I/O to finish or the tool-less model to suspend."""
        if self.task is None:
            return
        model = self.c.replay_model
        if model is None:
            await self.task
            self.task = None
            return
        waiting = asyncio.create_task(model.started.wait())
        try:
            done, _ = await asyncio.wait((self.task, waiting), return_when=asyncio.FIRST_COMPLETED)
            if self.task in done:
                await self.task
                self.task = None
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)

    async def run(self):
        try:
            while True:
                event = self.tape.events[self.index] if self.index < len(self.tape.events) else None
                model = self.c.replay_model
                pending = model.pending if model is not None else None
                timer = self.next_timer()
                times = [
                    t
                    for t in (
                        event.recorded_at if event else None,
                        pending[0] if pending else None,
                        timer,
                    )
                    if t is not None
                ]
                if not times:
                    break
                at = min(times)
                # Receipt first on equal timestamps. Orders created at completion cannot
                # fill from the already consumed event or a same-source-time quote.
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
                more_receipts = (
                    self.index < len(self.tape.events)
                    and self.tape.events[self.index].recorded_at == at
                )
                if pending is not None and pending[0] == at and not more_receipts:
                    self.clock[0] = at
                    pending[1].set_result(None)
                    # Completion must settle the native cycle before advancing again.
                    await self.task
                    self.task = None
            if self.clock[0] < self.tape.header.closes_at:
                await self.observe(self.tape.header.closes_at)
            return {
                "skipped_cycles": self.skipped,
                "model_scripts_used": sorted(model.used) if model else [],
            }
        finally:
            if self.task is not None:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)


async def run_replay(settings, tape, directory):
    """Freeze inputs before running independent clocks, then automatically export.

    First-session scripted evidence only. Existing targets are never adopted,
    overwritten or resumed. An interrupted directory retains admission and journals.
    """
    settings = ReplaySettings.model_validate(settings.model_dump(warnings=False))
    tape = RecordedTape.model_validate(tape.model_dump(warnings=False))
    manifest, header = settings.manifest, tape.header
    if (
        len(manifest.sessions) != 1
        or settings.narrow.arm != "B"
        or settings.broad.arm != "C"
        or manifest.experiment_id != header.experiment_id
        or manifest.declared_at != header.declared_at
        or (
            manifest.sessions[0].key,
            manifest.sessions[0].opens_at,
            manifest.sessions[0].closes_at,
            manifest.sessions[0].tape_hash,
        )
        != (header.session_key, header.opens_at, header.closes_at, tape.digest)
        or manifest.arms[0].limits.model_dump(exclude={"population_id", "account_id"})
        != header.limits.model_dump(exclude={"population_id", "account_id"})
    ):
        raise ValueError("One matched first-session tape and independent A/B/C scripts required")
    directory = Path(directory).absolute()
    directory.mkdir(mode=0o700)  # exclusive, never adopt any prior run
    _save(
        directory / "admission.json",
        {
            "status": "ADMITTED",
            "live_enabled": False,
            "evidence_kind": "LOCAL_FIXTURE",
            "model_evidence": "SCRIPTED",
            "settings": settings.model_dump(mode="json"),
            "tape": tape.model_dump(mode="json"),
        },
    )
    sources, owners, definitions, scheduling = {}, [], [], {}
    with ExitStack() as stack:
        for definition in manifest.arms:
            arm = definition.arm
            home = directory / arm
            home.mkdir(mode=0o700)
            clock = [header.opens_at]
            venue = DurableOptionVenue(
                home / "venue.db", limits=definition.limits, capital=definition.policy.capital
            )
            engine = stack.enter_context(
                OptionExecution.open(
                    home / "journal.db",
                    definition.limits,
                    definition.policy,
                    venue,
                    now=clock[0],
                    create=True,
                )
            )
            if not engine.reconcile(venue.snapshot(clock[0]), now=clock[0])["reconciled"]:
                raise ValueError("Fresh replay venue reconciliation required")
            engine.assess(None, None, now=clock[0])
            model = (
                None
                if arm == "A"
                else ReplayModel(settings.narrow if arm == "B" else settings.broad)
            )
            c = DegenCoordinator(
                engine,
                header.setup,
                header.selection,
                create=True,
                clock=lambda clock=clock: clock[0],
                replay_model=model,
                judgment_limits=settings.judgment_limits if model else None,
                entry_policy=settings.entry_policy if arm == "C" else None,
            )
            definitions.append(
                definition.model_copy(
                    update={"strategy_hash": strategy_hash(json.loads(c._configuration()))}
                )
            )
            sources[arm] = {
                "journal": str(home / "journal.db"),
                "data_cost": settings.data_cost_per_arm,
                "host_cost": settings.host_cost_per_arm,
            }
            owners.append((arm, _ArmReplay(c, venue, tape, clock)))
        # The fixture manifest's strategy hashes are derived from the exact enrolled
        # script/configuration before the first decision, never inferred from outcomes.
        manifest = EvaluationManifest.model_validate(
            manifest.model_copy(update={"arms": tuple(definitions)}).model_dump()
        )
        _save(directory / "manifest.json", manifest.model_dump(mode="json"))
        for arm, owner in owners:
            async with asyncio.timeout(900):
                scheduling[arm] = await owner.run()
    result = export_comparison(manifest, tape, sources)
    result["bundle"] = result["bundle"].model_dump(mode="json")
    result.update(model_evidence="SCRIPTED", scheduling=scheduling, live_enabled=False)
    _save(directory / "result.json", result)
    return result
