"""Create-only multi-session A/B/C replay through native isolated PAPER owners."""

import asyncio
import json
import os
import sqlite3
import time
from contextlib import ExitStack, closing
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, localcontext
from itertools import pairwise
from pathlib import Path

from pydantic import Field, model_validator

from app.execution.judgment import JudgmentLimits
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution
from app.options.entry_reasoning import EntryReasoningPolicy
from app.options.evaluation_export import export_series, strategy_hash
from app.options.evaluation_models import Arm, EvaluationManifest
from app.options.governor import _fresh, _tick_price
from app.options.lifecycle import TERMINAL, OptionIntent, OptionReceipt
from app.options.market_tape import validate_tape_series
from app.options.models import Money, OptionRecord
from app.options.replay_model import ReplayModel, ReplayScript
from app.options.venue import DurableOptionVenue


class ScriptedSettlement(OptionRecord):
    arm: Arm
    receipt: OptionReceipt

    @model_validator(mode="after")
    def funds_only(self):
        if (
            self.receipt.kind != "FUNDS_SETTLED"
            or self.receipt.contract is not None
            or self.receipt.quantity != 0
            or self.receipt.settlement_value is not None
            or self.receipt.cash_change <= 0
        ):
            raise ValueError("Explicit funds settlement only; no exercise or invented credits")
        return self


class ReplaySettings(OptionRecord):
    manifest: EvaluationManifest
    settlements: tuple[ScriptedSettlement, ...] = Field(default=(), max_length=180)
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


def _capture_boundary(journal, path):
    """Consistent private evidence copy only. Never copy the authority companion."""
    from app.options.observer import MAX_DATABASE_BYTES

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    deadline = time.monotonic() + 5

    def progress(_status, _remaining, total):
        if time.monotonic() >= deadline or total * page_size > MAX_DATABASE_BYTES:
            raise ValueError("Boundary snapshot deadline or capacity exceeded")

    with journal.read() as source, closing(sqlite3.connect(path)) as target:
        page_size = source.execute("PRAGMA page_size").fetchone()[0]
        source.execute("SELECT COUNT(*) FROM execution_events").fetchone()
        source.backup(target, pages=128, progress=progress, sleep=0)
        target.execute("PRAGMA journal_mode=DELETE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


async def run_replay(settings, tape, directory):
    """Compatible one-session entry point; never adopts an existing run."""
    return await run_replay_series(settings, (tape,), directory)


async def run_replay_series(settings, tapes, directory):
    """Replay an ordered predeclared series on the same three native owners.

    Bankroll, settled funds, costs, halts and sequence remain continuous. Only
    explicit between-session funds receipts change settled cash. Each close saves
    an evidence-only journal snapshot before the next session can change state.
    """
    settings = ReplaySettings.model_validate(settings.model_dump(warnings=False))
    tapes = validate_tape_series(tapes)
    manifest = settings.manifest
    if (
        len(tapes) != len(manifest.sessions)
        or settings.narrow.arm != "B"
        or settings.broad.arm != "C"
    ):
        raise ValueError("Exact bounded ordered session tapes and A/B/C scripts required")
    header = tapes[0].header
    for session, tape in zip(manifest.sessions, tapes, strict=True):
        h = tape.header
        if (
            manifest.experiment_id != h.experiment_id
            or manifest.declared_at != h.declared_at
            or (session.key, session.opens_at, session.closes_at, session.tape_hash)
            != (h.session_key, h.opens_at, h.closes_at, tape.digest)
            or manifest.arms[0].limits.model_dump(exclude={"population_id", "account_id"})
            != h.limits.model_dump(exclude={"population_id", "account_id"})
            or h.setup != header.setup
            or h.selection != header.selection
        ):
            raise ValueError("Matched frozen series and common market configuration required")
    receipts = settings.settlements
    if len({(r.arm, r.receipt.receipt_id) for r in receipts}) != len(receipts) or any(
        not any(
            previous.closes_at < r.receipt.occurred_at <= current.opens_at
            for previous, current in pairwise(manifest.sessions)
        )
        for r in receipts
    ):
        raise ValueError("Unique explicitly timed between-session settlements required")
    directory = Path(directory).absolute()
    directory.mkdir(mode=0o700)
    _save(
        directory / "admission.json",
        {
            "status": "ADMITTED",
            "live_enabled": False,
            "evidence_kind": "LOCAL_FIXTURE",
            "model_evidence": "SCRIPTED",
            "settings": settings.model_dump(mode="json"),
            "tapes": [t.model_dump(mode="json") for t in tapes],
        },
    )
    sources = {s.key: {} for s in manifest.sessions}
    scheduling = {s.key: {} for s in manifest.sessions}
    owners, definitions = [], []
    with ExitStack() as stack:
        for definition in manifest.arms:
            arm = definition.arm
            home = directory / arm
            home.mkdir(mode=0o700)
            (home / "sessions").mkdir(mode=0o700)
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
            owners.append((arm, c, venue, clock, home))
        manifest = EvaluationManifest.model_validate(
            manifest.model_copy(update={"arms": tuple(definitions)}).model_dump()
        )
        _save(directory / "manifest.json", manifest.model_dump(mode="json"))
        for arm, c, venue, clock, home in owners:
            for index, tape in enumerate(tapes):
                h = tape.header
                if index:
                    previous = tapes[index - 1].header
                    for scripted in sorted(
                        (
                            r
                            for r in receipts
                            if r.arm == arm
                            and previous.closes_at < r.receipt.occurred_at <= h.opens_at
                        ),
                        key=lambda r: r.receipt.occurred_at,
                    ):
                        receipt = scripted.receipt
                        if receipt.occurred_at < clock[0]:
                            raise ValueError("Settlement cannot precede the retained boundary")
                        clock[0] = receipt.occurred_at
                        venue.record_receipt(receipt)
                        if not c.engine.reconcile(venue.snapshot(clock[0]), now=clock[0])[
                            "reconciled"
                        ]:
                            raise ValueError("Settlement reconciliation required")
                    if clock[0] > h.opens_at:
                        raise ValueError("Prior session has not finished by the next open")
                    clock[0] = h.opens_at
                c._replay_quotes, c._replay_underlyings = {}, {}
                async with asyncio.timeout(900):
                    scheduling[h.session_key][arm] = await _ArmReplay(c, venue, tape, clock).run()
                boundary = home / "sessions" / (h.session_key + ".db")
                _capture_boundary(c.engine.journal, boundary)
                sources[h.session_key][arm] = {
                    "journal": str(boundary),
                    "data_cost": settings.data_cost_per_arm,
                    "host_cost": settings.host_cost_per_arm,
                }
                _save(
                    home / "sessions" / (h.session_key + ".json"),
                    {
                        "session_key": h.session_key,
                        "captured_at": clock[0].isoformat(),
                        "execution_authority": False,
                        "scheduling": scheduling[h.session_key][arm],
                    },
                )
    result = export_series(manifest, tapes, sources)
    result["bundle"] = result["bundle"].model_dump(mode="json")
    result.update(
        model_evidence="SCRIPTED",
        scheduling=scheduling if len(tapes) > 1 else scheduling[header.session_key],
        live_enabled=False,
    )
    _save(directory / "result.json", result)
    return result
