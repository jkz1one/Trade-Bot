"""Four independent native mixed owners consuming one sealed session sequence."""

import asyncio
import json
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.options.models import paper_market_evidence
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.mixed.market_tape import MixedRecordedTape, validate_series
from app.mixed.replay_enrollment import MixedReplayEnrollment
from app.mixed.replay_export import export_mixed_execution
from app.mixed.replay_model import MixedReplayModel, MixedReplayScript
from app.mixed.sources import StockCycleInput
from app.mixed.stock_models import StockIntent
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, exact, fingerprint
from app.options.entry_reasoning import EntryReasoningPolicy
from app.options.governor import _fresh
from app.options.lifecycle import TERMINAL, OptionExecutionPolicy, OptionIntent
from app.options.models import OptionLimits, OptionRecord
from app.options.position_reasoning import PositionReasoningPolicy
from app.options.replay import ScriptedSettlement, _ArmReplay, _save, fill_quantity
from app.options.scope_arbitration import SharedScopePolicy
from app.options.scope_replay import _perform, _revision
from app.options.scope_runtime import protection
from app.options.scope_tape_watch import ScopeTapeWatchAction, _resolve
from app.options.venue import DurableOptionVenue

MAX_REQUEST_BYTES = 64 * 1024 * 1024


def carry_boundary(previous, header):
    """A carried holding must visit its next original session without invented coverage."""
    ledger = previous["report"]["ledger"]
    stock = ledger.get("stock_position")
    option = ledger.get("position")
    position = stock or option
    status = "NO_HELD_POSITION"
    if position is not None:
        terms = stock["entry"].get("carry") if stock else option.get("swing_carry")
        deadline = stock["entry"]["exit_at"] if stock else option["exit_at"]
        if terms is None:
            status = "UNRESOLVED_INTRADAY_EXPOSURE"
        elif datetime.fromisoformat(deadline) <= datetime.fromisoformat(previous["as_of"]):
            status = "UNRESOLVED_CARRY_EXIT"
        else:
            future = [
                s
                for s in terms["sessions"]
                if datetime.fromisoformat(s["opens_at"]) > datetime.fromisoformat(previous["as_of"])
            ]
            if not future or (
                future[0]["session"],
                datetime.fromisoformat(future[0]["opens_at"]),
                datetime.fromisoformat(future[0]["closes_at"]),
            ) != (header.session_key, header.opens_at, header.closes_at):
                raise ValueError(
                    "Carried mixed holding requires its next original enumerated session"
                )
            status = "ORIGINAL_STOCK_CARRY" if stock else "ORIGINAL_SWING_CARRY"
    return {
        "ownership_status": status,
        "position": position,
        "coverage": "NOT_CONTINUOUSLY_OBSERVED" if position else "NO_HELD_POSITION",
        "overnight_return": None,
        "overnight_drawdown": None,
    }


class MixedReplaySession(OptionRecord):
    tape: MixedRecordedTape
    watch_actions: tuple[ScopeTapeWatchAction, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def watches(self):
        if len({a.key for a in self.watch_actions}) != len(self.watch_actions) or any(
            a.at > b.at or (a.at == b.at and (a.sequence or 0) > (b.sequence or 0))
            for a, b in pairwise(self.watch_actions)
        ):
            raise ValueError("Ordered unique original mixed watch actions required")
        for action in self.watch_actions:
            _resolve(self.tape, action)
        return self


class MixedReplayAccount(OptionRecord):
    arm: Literal["A", "B", "C", "D"]
    limits: OptionLimits
    execution: OptionExecutionPolicy
    scope: SharedScopePolicy | None = None
    judgment_limits: JudgmentLimits | None = None
    entry_policy: EntryReasoningPolicy | None = None
    position_policy: PositionReasoningPolicy | None = None
    script: MixedReplayScript | None = None

    @model_validator(mode="after")
    def complete_role(self):
        if self.execution.mixed_owner is not None and self.execution.mixed_owner.portfolio is not None:
            raise ValueError("Historical mixed replay v1 cannot reinterpret portfolio enrollment; use the portfolio v2 protocol")
        paid = self.arm != "A"
        if (
            self.execution.mixed_owner is None
            or any(
                (value is not None) != paid
                for value in (
                    self.execution.cost_policy,
                    self.execution.mixed_owner.reasoning,
                    self.judgment_limits,
                    self.entry_policy,
                    self.script,
                )
            )
            or (self.position_policy is not None) != (self.arm == "D")
        ):
            raise ValueError("One explicit native mixed owner and complete A/B/C/D role required")
        if paid and (
            self.script.arm != self.arm
            or self.entry_policy.mixed_selection != "mixed-paid-entry-v1"
            or (self.entry_policy.mixed_shortlist is not None) != (self.arm == "B")
            or (self.position_policy is not None and self.position_policy.mixed_management is None)
        ):
            raise ValueError("Exact full mixed response contracts required")
        if self.scope is not None and (
            self.scope.version != ("shared-scope-entry-v1" if paid else "shared-scope-selection-v1")
            or self.execution.scope_arbitration != self.scope.version
            or (paid and self.entry_policy.scope_selection != "scope-fixed-plan-v1")
        ):
            raise ValueError("Original fixed Scope owner and full response contract required")
        if (self.scope is not None) != (self.execution.scope_arbitration is not None):
            raise ValueError("Complete Scope native enrollment required")
        if (
            self.entry_policy is not None
            and ((self.scope is not None) != (self.entry_policy.scope_selection is not None))
            or self.position_policy is not None
            and ((self.scope is not None) != (self.position_policy.scope_management is not None))
        ):
            raise ValueError("Complete original Scope entry and management roles required")
        return self


def comparable_execution(policy):
    value = policy.model_dump(mode="json", exclude={"cost_policy", "scope_arbitration"})
    value["mixed_owner"].pop("reasoning", None)
    # Model-off A has no paid calls to attribute; the underlying loss limits stay matched.
    if value.get("loss_control") is not None:
        value["loss_control"].pop("entry_cost_attribution", None)
    return value


class MixedComparison(OptionRecord):
    version: Literal["mixed-independent-series-v1"] = "mixed-independent-series-v1"
    sessions: tuple[MixedReplaySession, ...] = Field(min_length=1, max_length=60)
    accounts: tuple[MixedReplayAccount, ...] = Field(min_length=4, max_length=4)
    settlements: tuple[ScriptedSettlement, ...] = Field(default=(), max_length=180)

    @model_validator(mode="after")
    def matched(self):
        tapes = validate_series(tuple(s.tape for s in self.sessions))
        h = tapes[0].header
        if tuple(a.arm for a in self.accounts) != tuple("ABCD") or any(
            len({getattr(a.limits, name) for a in self.accounts}) != 4
            for name in ("population_id", "account_id")
        ):
            raise ValueError("Four distinct ordered native A/B/C/D accounts required")
        a, b, c, d = self.accounts
        for account in self.accounts:
            from app.options.scope_carry import validate_policy

            validate_policy(
                account.execution,
                account.scope,
                h.swing,
                account.entry_policy,
                account.position_policy,
            )
            carrying = h.swing is not None and h.swing.carry is not None
            if (
                carrying != (account.execution.swing_carry is not None)
                or (
                    account.scope is not None
                    and (h.swing is not None) != ("SWING" in account.scope.family_priority)
                )
                or (
                    carrying
                    and account.entry_policy is not None
                    and account.entry_policy.max_carry_horizon_seconds is None
                )
                or (
                    carrying
                    and account.position_policy is not None
                    and account.position_policy.swing_carry is None
                )
            ):
                raise ValueError("Complete original family/carry replay enrollment required")
            if (
                account.limits.model_dump(exclude={"population_id", "account_id"})
                != h.limits.model_dump(exclude={"population_id", "account_id"})
                or account.execution.mixed_owner.stocks != h.stock_limits
                or comparable_execution(account.execution) != comparable_execution(a.execution)
                or (account.scope is not None) != (h.scope is not None)
                or (
                    account.scope is not None
                    and (
                        account.scope.watch != h.scope.watch
                        or account.scope.family_priority != h.stocks.family_priority
                        or account.scope.model_dump(exclude={"version"})
                        != a.scope.model_dump(exclude={"version"})
                    )
                )
            ):
                raise ValueError(
                    "Matched source, capital, risk, fees and daily allocations required"
                )
        for account in (b, d):
            if (
                account.execution.cost_policy != c.execution.cost_policy
                or account.judgment_limits != c.judgment_limits
                or account.execution.loss_control != c.execution.loss_control
                or account.entry_policy.model_dump(exclude={"mixed_shortlist"})
                != c.entry_policy.model_dump(exclude={"mixed_shortlist"})
            ):
                raise ValueError(
                    "Matched paid costs, deadlines and full entry configuration required"
                )
        if {x.cycle_key: x for x in c.script.decisions} != {
            x.cycle_key: x for x in d.script.decisions if x.cycle_key.startswith("degen:")
        }:
            raise ValueError("C/D declared entry responses, delays and usage must match")
        slots = {e.cycle_key.split(":")[1] for t in tapes for e in t.events if e.kind == "CYCLE"}
        if any(
            x.cycle_key.split(":")[1] not in slots
            for account in (b, c, d)
            for x in account.script.decisions
        ):
            raise ValueError("Scripts must name original recorded decision slots")
        actions = [x for s in self.sessions for x in s.watch_actions]
        if len({x.key for x in actions}) != len(actions):
            raise ValueError("Watch action keys cannot repeat across mixed sessions")
        if len({(s.arm, s.receipt.receipt_id) for s in self.settlements}) != len(
            self.settlements
        ) or any(
            not any(
                left.header.closes_at < s.receipt.occurred_at <= right.header.opens_at
                for left, right in pairwise(tapes)
            )
            for s in self.settlements
        ):
            raise ValueError("Explicit unique between-session funds settlements required")
        if len(self.model_dump_json().encode()) > MAX_REQUEST_BYTES:
            raise ValueError("Mixed comparison request capacity exceeded")
        return self


@exact
def stock_fill_quantity(intent, order, snapshot, quote, at, limits):
    if (
        quote.instrument != intent.instrument
        or not intent.prepared_at < quote.source_at <= quote.received_at <= at
        or not order.updated_at <= at < intent.order_expires_at
        or quote.source != limits.quote_source
        or not paper_market_evidence(quote)
        or not quote.complete
        or not _fresh(
            quote.source_at,
            quote.received_at,
            at,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        return Decimal(0)
    buy = intent.side == "BUY"
    if buy and (
        quote.bid < limits.minimum_price
        or (quote.ask - quote.bid) / quote.ask > limits.max_spread_fraction
    ):
        return Decimal(0)
    raw, size = (quote.ask, quote.ask_size) if buy else (quote.bid, quote.bid_size)
    if size is None:
        return Decimal(0)
    price = raw * (1 + (1 if buy else -1) * limits.slippage_bps / 10000)
    price = (price / intent.instrument.tick).to_integral_value(
        rounding=ROUND_CEILING if buy else ROUND_FLOOR
    ) * intent.instrument.tick
    if (
        price <= 0
        or (buy and price > intent.limit_price)
        or (not buy and price < intent.limit_price)
    ):
        return Decimal(0)
    consumed = Decimal(0)
    for previous in snapshot.stock_orders:
        if previous.side != intent.side:
            continue
        for fill in previous.fills:
            old = fill.quote
            if old.instrument != quote.instrument or old.source_at != quote.source_at:
                continue
            if any(
                getattr(old, k) != getattr(quote, k) for k in ("bid", "ask", "bid_size", "ask_size")
            ):
                raise ValueError("Mixed replay stock source quote conflicts with prior fills")
            consumed += fill.quantity
    quantity = max(Decimal(0), min(size - consumed, order.quantity - order.filled_quantity))
    return (quantity / limits.share_step).to_integral_value(
        rounding=ROUND_FLOOR
    ) * limits.share_step


class MixedArmReplay(_ArmReplay):
    def __init__(self, coordinator, venue, session, clock):
        super().__init__(coordinator, venue, session.tape, clock)
        self.instructions = session.watch_actions
        self.resolved = tuple(_resolve(self.tape, a) for a in self.instructions)
        self.action_index = self.received_sequence = 0
        self.actions, self.fresh_reads = [], []
        self.stocks, self.stock_observations, self.scope_observations = {}, {}, {}

    def intents(self):
        with self.c.engine.journal.read() as db:
            return {
                r[0]: model.model_validate_json(r[1])
                for table, model in (
                    ("execution_orders", OptionIntent),
                    ("execution_stock_orders", StockIntent),
                )
                for r in db.execute("SELECT client_id,intent_json FROM " + table)
            }

    def next_timer(self):
        timers = [super().next_timer()]
        snapshot = self.venue.snapshot(self.clock[0])
        times = [
            o.intent.order_expires_at for o in snapshot.stock_orders if o.status not in TERMINAL
        ]
        if snapshot.stock_position is not None:
            times.append(snapshot.stock_position.entry.exit_at)
        if self.action_index < len(self.instructions):
            times.append(self.instructions[self.action_index].at)
        timers.extend(
            t
            for t in times
            if self.clock[0] < t <= self.tape.header.closes_at + timedelta(seconds=5)
        )
        return min((t for t in timers if t is not None), default=None)

    async def fresh_stock(self, instrument):
        saved = self.stock_observations.get(instrument.instrument_id)
        if (
            saved is None
            or saved[0].recorded_at > self.clock[0]
            or saved[1].instrument != instrument
        ):
            raise ExecutionBlocked("MIXED_DELIVERED_STOCK_OBSERVATION_REQUIRED")
        event, quote = saved
        self._fresh_receipt(event, "STOCK", fingerprint(quote))
        return quote

    async def fresh_scope(self, play_key):
        event = self.scope_observations.get(play_key)
        if event is None or event.recorded_at > self.clock[0]:
            raise ExecutionBlocked("MIXED_DELIVERED_SCOPE_OBSERVATION_REQUIRED")
        self._fresh_receipt(event, "SCOPE", fingerprint(event.frame.scope))
        return event.frame.scope

    def _fresh_receipt(self, event, asset, digest):
        self.fresh_reads.append(
            {
                "asset": asset,
                "at": self.clock[0].isoformat(),
                "sequence": event.sequence,
                "event_hash": fingerprint(event),
                "input_hash": digest,
                "tape_hash": self.tape.digest,
            }
        )

    async def observe(self, at, event=None):
        # Deliver a real same-clock opening receipt before assessing a carried
        # holding. A missing/later receipt still takes the native stale-input path.
        if (
            event is None
            and self.received_sequence == 0
            and at == self.tape.header.opens_at
            and self.tape.events
            and self.tape.events[0].recorded_at == at
        ):
            return
        self.clock[0] = at
        quotes, underlyings, stocks = (), (), ()
        if event is not None:
            self.received_sequence = event.sequence
            quotes, underlyings = protection(event.frame)
            stocks = tuple(i.quote for i in event.frame.stocks)
            self.quotes.update((q.instrument.instrument_id, q) for q in quotes)
            self.underlyings.update((q.symbol, q) for q in underlyings)
            self.stocks.update((q.instrument.instrument_id, q) for q in stocks)
            self.stock_observations.update((q.instrument.instrument_id, (event, q)) for q in stocks)
            if event.frame.scope is not None:
                self.scope_observations[event.frame.scope.play_key] = event
            self.c._replay_quotes, self.c._replay_underlyings = (
                dict(self.quotes),
                dict(self.underlyings),
            )
        intents = self.intents()
        snapshot = self.venue.snapshot(at)
        for order in (*snapshot.orders, *snapshot.stock_orders):
            if order.status in TERMINAL:
                continue
            intent = intents[order.client_id]
            stock = isinstance(intent, StockIntent)
            if at >= intent.order_expires_at:
                terminal = self.venue.record_stock_terminal if stock else self.venue.record_terminal
                terminal(order.client_id, "EXPIRED", at)
                continue
            for quote in stocks if stock else quotes:
                snap = self.venue.snapshot(at)
                current = next(
                    o
                    for o in (snap.stock_orders if stock else snap.orders)
                    if o.client_id == order.client_id
                )
                quantity = (stock_fill_quantity if stock else fill_quantity)(
                    intent,
                    current,
                    snap,
                    quote,
                    at,
                    self.c.engine.policy.mixed_owner.stocks if stock else self.c.engine.limits,
                )
                if not quantity:
                    continue
                fill_id = f"mixed-{self.tape.header.session_key}-{event.sequence}-{order.client_id}"
                if stock:
                    self.venue.fill_stock(intent, quantity, quote, at, fill_id=fill_id)
                else:
                    from app.options.fill_evidence import validate_underlying

                    underlying = self.underlyings.get(intent.instrument.contract.underlying)
                    if underlying is not None:
                        try:
                            validate_underlying(self.c.engine.limits, intent, quote, underlying, at)
                        except ValueError:
                            underlying = None
                    self.venue.fill(
                        intent, quantity, quote, at, fill_id=fill_id, underlying=underlying
                    )
        if not (await self.c.engine.reconcile_fixture(now=at))["reconciled"]:
            raise ValueError("Mixed replay failed authoritative reconciliation")
        held = self.venue.snapshot(at).position
        held_quote = (
            self.quotes.get(intents[held.entry_client_id].instrument.instrument_id)
            if held
            else None
        )
        result = await self.c.supervise(
            (held_quote,) if held_quote is not None else (),
            tuple(self.underlyings.values()),
            stocks=tuple(StockCycleInput(quote=q) for q in self.stocks.values()),
        )
        if result.get("reconciled") is False:
            raise ValueError("Mixed replay failed authoritative reconciliation")
        while self.action_index < len(self.instructions):
            action = self.instructions[self.action_index]
            if action.at > at or (action.sequence or 0) > self.received_sequence:
                break
            if action.at != at:
                raise ValueError("Mixed watch instruction missed its original clock")
            step, binding = self.resolved[self.action_index]
            revision = _revision(self.c.engine)
            try:
                result = {
                    "status": "RECORDED",
                    "receipt": _perform(self.c.scope_book, step, revision),
                }
            except ExecutionBlocked as exc:
                if _revision(self.c.engine) != revision:
                    raise ValueError("Rejected watch instruction changed native state") from exc
                result = {"status": "REJECTED", "reason": str(exc)}
            self.actions.append(
                {
                    "key": action.key,
                    "instruction_hash": fingerprint(action),
                    "binding": binding,
                    "expected_revision": revision,
                    **result,
                }
            )
            self.action_index += 1

    async def run(self):
        await self.observe(self.clock[0])
        result = await super().run()
        if self.action_index != len(self.instructions):
            raise ValueError("Mixed replay did not consume every watch instruction")
        with self.c.engine.journal.read() as db:
            for row in db.execute("SELECT result_json FROM execution_option_opportunities"):
                if row[0] and json.loads(row[0]).get("reason") == "DEGEN_CYCLE_FAILED":
                    raise ValueError("Mixed replay native cycle failed")
        self.c.engine.refresh_loss_control(now=self.clock[0])
        return result | {"watch_actions": self.actions, "fresh_reads": self.fresh_reads}


async def _unbound(_identity):
    raise ValueError("Mixed tape reader must bind before the first cycle")


async def run_mixed_comparison(request, directory):
    from app.mixed.comparison import MAX_BUNDLE_BYTES, comparison_report

    request = MixedComparison.model_validate(request.model_dump(warnings=False))
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute new mixed replay directory required")
    directory.mkdir(mode=0o700)
    digest = fingerprint(request)
    _save(
        directory / "inputs.json",
        {"request_hash": digest, "request": request.model_dump(mode="json")},
    )
    h = request.sessions[0].tape.header
    boundaries = [{} for _ in request.sessions]
    schedules = [{} for _ in request.sessions]
    retained_bytes = len(request.model_dump_json().encode())
    try:
        for account in request.accounts:
            path = directory / account.arm
            path.mkdir(mode=0o700)
            clock = [h.opens_at]
            venue = DurableOptionVenue(
                path / "venue.db",
                limits=account.limits,
                stock_limits=h.stock_limits,
                capital=account.execution.capital,
            )
            model = MixedReplayModel(account.script) if account.script is not None else None
            enrollment = (
                MixedReplayEnrollment(
                    tape_hashes=tuple(s.tape.digest for s in request.sessions),
                    request_hash=digest,
                    script_hash=fingerprint(account.script),
                )
                if model
                else None
            )
            with OptionExecution.open(
                path / "options.db",
                account.limits,
                account.execution,
                venue,
                now=clock[0],
                create=True,
            ) as engine:
                if not engine.reconcile(venue.snapshot(clock[0]), now=clock[0])["reconciled"]:
                    raise ValueError("Initial mixed native reconciliation required")
                engine.assess_stock(None, now=clock[0])
                stocks = (
                    h.stocks.model_copy(update={"paid_selection": "mixed-paid-entry-v1"})
                    if model
                    else h.stocks
                )
                c = DegenCoordinator(
                    engine,
                    h.setup,
                    h.selection,
                    create=True,
                    clock=lambda clock=clock: clock[0],
                    stock_policy=stocks,
                    swing_policy=h.swing,
                    scope_policy=account.scope,
                    judgment_limits=account.judgment_limits,
                    entry_policy=account.entry_policy,
                    position_policy=account.position_policy,
                    replay_model=model,
                    mixed_replay=enrollment,
                    stock_refresh=_unbound if model else None,
                    scope_refresh=_unbound if model and account.scope else None,
                )
                settled = set()
                for index, session in enumerate(request.sessions):
                    if index:
                        carry_boundary(boundaries[index - 1][account.arm], session.tape.header)
                    for settlement in sorted(
                        (s for s in request.settlements if s.arm == account.arm),
                        key=lambda s: s.receipt.occurred_at,
                    ):
                        r = settlement.receipt
                        if (
                            r.receipt_id not in settled
                            and r.occurred_at <= session.tape.header.opens_at
                        ):
                            clock[0] = r.occurred_at
                            venue.record_receipt(r)
                            if not (await engine.reconcile_fixture(now=clock[0]))["reconciled"]:
                                raise ValueError(
                                    "Explicit mixed funds settlement did not reconcile"
                                )
                            settled.add(r.receipt_id)
                    clock[0] = session.tape.header.opens_at
                    replay = MixedArmReplay(c, venue, session, clock)
                    if model:
                        c.stock_refresh = replay.fresh_stock
                        if account.scope:
                            c.scope_refresh = replay.fresh_scope
                    async with asyncio.timeout(900):
                        schedules[index][account.arm] = await replay.run()
                    exported = export_mixed_execution(engine.journal, now=clock[0])
                    retained_bytes += len(
                        json.dumps(
                            {"export": exported, "schedule": schedules[index][account.arm]},
                            allow_nan=False,
                        ).encode()
                    )
                    if retained_bytes > MAX_BUNDLE_BYTES:
                        raise ValueError("Mixed comparison evidence capacity exceeded")
                    boundaries[index][account.arm] = exported
                    _save(path / (session.tape.header.session_key + ".json"), exported)
        report = comparison_report(request, boundaries, schedules)
        bundle = {
            "version": "mixed-comparison-bundle-v1",
            "request": request.model_dump(mode="json"),
            "boundaries": boundaries,
            "schedules": schedules,
            "report": report,
        }
        bundle["bundle_hash"] = fingerprint(bundle)
        if len(json.dumps(bundle, allow_nan=False).encode()) > MAX_BUNDLE_BYTES:
            raise ValueError("Mixed comparison bundle capacity exceeded")
        _save(directory / "comparison.json", bundle)
        return bundle
    except BaseException:
        _save(
            directory / "interrupted.json",
            {"request_hash": digest, "status": "INCOMPLETE_MIXED_REPLAY"},
        )
        raise
