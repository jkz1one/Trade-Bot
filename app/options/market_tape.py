"""Create-only, sealed local market evidence. No provider or execution authority."""

import json
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.options.coordinator import DegenFrame
from app.options.degen import DegenPolicy, scan_degen
from app.options.engine import clock, fingerprint
from app.options.entry_reasoning import Digest
from app.options.models import Name, OptionLimits, OptionRecord
from app.options.scope_market_tape import ScopeTapePolicy, validate_header, validate_scope_event
from app.options.selection import ContractSelectionPolicy, plan_contract_reads
from app.options.swing import SwingPolicy, plan_swing_reads, scan_swing, seed_issues
from app.robinhood.schedule import XNYSCalendar

MAX_TAPE_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
MAX_EVENTS = 4096


class TapeHeader(OptionRecord):
    version: Literal["option-market-tape-v1"] = "option-market-tape-v1"
    evidence_kind: Literal["LOCAL_FIXTURE"] = "LOCAL_FIXTURE"
    experiment_id: Name
    session_key: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    declared_at: datetime
    opens_at: datetime
    closes_at: datetime
    limits: OptionLimits
    setup: DegenPolicy
    selection: ContractSelectionPolicy
    swing: SwingPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    scope: ScopeTapePolicy | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def coherent(self):
        window = XNYSCalendar().current_window(self.opens_at)
        if (
            window is None
            or (self.session_key, self.opens_at, self.closes_at)
            != (window.session_date, window.opens_at, window.closes_at)
            or self.declared_at >= self.opens_at
            or not set(self.setup.symbols) <= set(self.limits.allowed_underlyings)
            or (
                self.selection.max_quote_contracts
                + (2 if self.swing and self.swing.family_batch else 1 if self.swing else 0)
            )
            * len(self.setup.symbols)
            + (1 if self.scope else 0)
            > 8
        ):
            raise ValueError("Frozen complete session and bounded universe required")
        if self.scope is not None:
            validate_header(self)
        return self


class TapeEvent(OptionRecord):
    sequence: int = Field(ge=1, le=MAX_EVENTS, strict=True)
    previous_hash: Digest
    recorded_at: datetime
    kind: Literal["CYCLE", "MARKET", "SCOPE"]
    frame: DegenFrame

    @property
    def cycle_key(self):
        return "degen:" + str(int(self.recorded_at.timestamp()) // 300)


class TapeSeal(OptionRecord):
    header_hash: Digest
    event_count: int = Field(ge=0, le=MAX_EVENTS, strict=True)
    last_hash: Digest


def _validate_event(header, event):
    at, frame = event.recorded_at, event.frame
    if frame.stocks:
        raise ValueError("Stock frames require separate mixed tape enrollment")
    if not header.opens_at <= at <= header.closes_at + timedelta(seconds=5):
        raise ValueError("Observation outside recorded session")
    if event.kind == "CYCLE" and at >= header.closes_at:
        raise ValueError("Cycle outside regular session")
    if event.kind == "MARKET" and (
        frame.histories
        or frame.inventories
        or frame.swing
        or frame.swing_batches
        or frame.scope is not None
    ):
        raise ValueError("Market updates contain quotes only")
    if event.kind == "SCOPE" and (
        frame.scope is None
        or frame.histories
        or frame.inventories
        or frame.swing
        or frame.swing_batches
        or frame.quotes
        or frame.underlyings
    ):
        raise ValueError("Scope observations require only the nested Scope input")
    validate_scope_event(header, event)
    if frame.swing and header.swing is None:
        raise ValueError("Swing evidence requires frozen shared-family enrollment")
    if len({s.seed.history.symbol for s in frame.swing}) != len(frame.swing):
        raise ValueError("Duplicate Swing seed identity")
    from app.options.swing_batch import frame_items

    items = (
        frame_items(frame, header.swing, XNYSCalendar(), header.setup.symbols, at)
        if event.kind == "CYCLE"
        else ()
    )
    for item in items:
        seed, history = item.seed, item.seed.history
        from app.options.swing_targets import target_issues

        if (header.swing.family_batch is None or seed.batch_hash is None) and target_issues(
            seed, header.swing
        ):
            raise ValueError("Swing target derivation must match frozen tape enrollment")
        if (
            history.symbol not in header.setup.symbols
            or seed.instrument.contract.underlying != history.symbol
            or item.metadata.instrument != seed.instrument
            or (item.catalyst is None if header.swing.input_basis is None else item.catalyst is not None)
            or (item.catalyst is not None and item.catalyst.symbol != history.symbol)
            or seed.created_at > at
            or not history.received_at <= seed.created_at
        ):
            raise ValueError("Foreign or unavailable Swing identity")
        for evidence, source in (
            (history, header.swing.history_source),
            (item.metadata, header.selection.metadata_source),
            (item.catalyst, header.swing.catalyst_source),
        ):
            if evidence is None:
                continue
            if evidence.source != source or not evidence.source_at <= evidence.received_at <= at:
                raise ValueError("Foreign or unavailable Swing evidence")
        if any(b.closes_at > min(history.source_at, history.received_at) for b in history.bars):
            raise ValueError("Only completed recorded daily bars are replayable")
    groups = (
        (frame.histories, lambda x: x.symbol, header.setup.history_source),
        (frame.inventories, lambda x: x.symbol, header.selection.metadata_source),
        (frame.quotes, lambda x: x.instrument.instrument_id, header.limits.option_source),
        (frame.underlyings, lambda x: x.symbol, header.limits.underlying_source),
    )
    for items, identity, source in groups:
        if len({identity(x) for x in items}) != len(items):
            raise ValueError("Duplicate market identity")
        for item in items:
            symbol = (
                item.instrument.contract.underlying if hasattr(item, "instrument") else item.symbol
            )
            # SPY quotes are retained even if the strategy trades QQQ only.
            allowed = set(header.setup.symbols) | ({"SPY"} if items is frame.underlyings else set())
            if header.scope is not None and (items is frame.quotes or items is frame.underlyings):
                allowed.add("SPX")
            if symbol not in allowed or item.source != source:
                raise ValueError("Foreign market source or universe")
            if not item.source_at <= item.received_at <= at:
                raise ValueError("Market evidence unavailable at recording time")
    for quote in frame.quotes:
        if quote.instrument.contract.underlying == "SPX" and header.scope is not None:
            from app.options.scope_market_tape import validate_instrument

            validate_instrument(header, quote.instrument)
        g = quote.greeks
        if g is not None and (
            g.source != header.limits.option_source
            or not g.source_at <= g.received_at <= quote.received_at
        ):
            raise ValueError("Greek evidence foreign or unavailable at quote receipt")
    for h in frame.histories:
        if any(b.ends_at > min(h.source_at, h.received_at) for b in h.bars):
            raise ValueError("Only completed recorded bars are replayable")
    for inventory in frame.inventories:
        if len({m.instrument.instrument_id for m in inventory.contracts}) != len(
            inventory.contracts
        ):
            raise ValueError("Duplicate inventory identity")
        for m in inventory.contracts:
            if (
                m.instrument.contract.underlying != inventory.symbol
                or m.source != header.selection.metadata_source
                or not m.source_at <= m.received_at <= inventory.received_at
            ):
                raise ValueError("Foreign or unavailable inventory metadata")


class RecordedTape(OptionRecord):
    header: TapeHeader
    events: tuple[TapeEvent, ...] = Field(max_length=MAX_EVENTS)
    seal: TapeSeal

    def _validate_event(self, event):
        _validate_event(self.header, event)

    @model_validator(mode="after")
    def verified(self):
        previous, at, keys = fingerprint(self.header), self.header.opens_at, set()
        for n, event in enumerate(self.events, 1):
            if event.sequence != n or event.previous_hash != previous or event.recorded_at < at:
                raise ValueError("Broken market sequence, hash chain or clock")
            self._validate_event(event)
            if event.kind == "CYCLE":
                if event.cycle_key in keys:
                    raise ValueError("Duplicate recorded cycle")
                keys.add(event.cycle_key)
            previous, at = fingerprint(event), event.recorded_at
        if self.seal != TapeSeal(
            header_hash=fingerprint(self.header), event_count=len(self.events), last_hash=previous
        ):
            raise ValueError("Missing or mismatched tape seal")
        if len(self.model_dump_json().encode()) > MAX_TAPE_BYTES:
            raise ValueError("Market tape capacity exceeded")
        return self

    @property
    def digest(self):
        return fingerprint(self.seal)

    def available(self, at):
        """Expose only the prefix recorded by this instant, including receipt latency."""
        at = clock(at)
        return tuple(e for e in self.events if e.recorded_at <= at)


def _line(kind, value):
    raw = (
        json.dumps({"kind": kind, "value": value.model_dump(mode="json")}, sort_keys=True).encode()
        + b"\n"
    )
    if len(raw) > MAX_LINE_BYTES:
        raise ValueError("Market event capacity exceeded")
    return raw


class TapeRecorder:
    """New private file only. Every successful append is fsynced; close never adds a seal.

    Timestamps/normalized frames are supplied fixture evidence, not authenticated
    acquisition. No reopen/append, automatic resume, pruning or overwrite API exists.
    """

    header_type = TapeHeader
    validate_event = staticmethod(_validate_event)

    def __init__(self, path, header):
        self.header = self.header_type.model_validate(header.model_dump(warnings=False))
        self._fd = None
        self._size = self._count = 0
        self._previous = fingerprint(self.header)
        self._at, self._keys = self.header.opens_at, set()
        self._failed = False
        path = Path(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(directory)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("Existing private tape directory required")
            self._fd = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            os.fchmod(self._fd, 0o600)
            self._write("HEADER", self.header)
            os.fsync(directory)
        except BaseException:
            self.close()
            raise
        finally:
            os.close(directory)

    def _write(self, kind, value):
        if self._fd is None or self._failed:
            raise ValueError("Tape recorder closed or interrupted")
        raw = _line(kind, value)
        # Keep room for a seal, even when refusing a further observation.
        if self._size + len(raw) > MAX_TAPE_BYTES - (MAX_LINE_BYTES if kind != "SEAL" else 0):
            raise ValueError("Market tape capacity exceeded")
        try:
            view = memoryview(raw)
            while view:
                written = os.write(self._fd, view)
                if written <= 0:
                    raise OSError("Short market evidence write")
                view = view[written:]
            os.fsync(self._fd)
        except BaseException:
            self._failed = True
            raise
        self._size += len(raw)

    def append(self, frame, *, recorded_at, kind="CYCLE"):
        event = TapeEvent(
            sequence=self._count + 1,
            previous_hash=self._previous,
            recorded_at=recorded_at,
            kind=kind,
            frame=frame,
        )
        event = TapeEvent.model_validate(event.model_dump(warnings=False))
        self.validate_event(self.header, event)
        if event.recorded_at < self._at or (kind == "CYCLE" and event.cycle_key in self._keys):
            raise ValueError("Regressing clock or duplicate cycle")
        self._write("EVENT", event)
        self._count, self._previous, self._at = (
            event.sequence,
            fingerprint(event),
            event.recorded_at,
        )
        if kind == "CYCLE":
            self._keys.add(event.cycle_key)
        return event

    def seal(self):
        seal = TapeSeal(
            header_hash=fingerprint(self.header), event_count=self._count, last_hash=self._previous
        )
        self._write("SEAL", seal)
        self.close()
        return fingerprint(seal)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _read_records(path):
    """Read bounded sealed records without selecting or broadening their contract."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= MAX_TAPE_BYTES
        ):
            raise ValueError("Bounded private regular tape required")
        records, consumed = [], 0
        while raw := stream.readline(MAX_LINE_BYTES + 1):
            consumed += len(raw)
            if (
                len(raw) > MAX_LINE_BYTES
                or consumed > MAX_TAPE_BYTES
                or not raw.endswith(b"\n")
                or len(records) >= MAX_EVENTS + 2
            ):
                raise ValueError("Truncated or oversized tape")
            row = json.loads(raw)
            if not isinstance(row, dict) or set(row) != {"kind", "value"}:
                raise ValueError("Invalid tape envelope")
            records.append(row)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Tape changed while reading")
    if (
        len(records) < 2
        or records[0]["kind"] != "HEADER"
        or records[-1]["kind"] != "SEAL"
        or any(r["kind"] != "EVENT" for r in records[1:-1])
    ):
        raise ValueError("Sealed tape required; interrupted prefixes cannot be resumed")
    return records


def load_tape(path):
    """Read a sealed artifact without any source journal, credentials or writable handle."""
    records = _read_records(path)
    return RecordedTape(
        header=records[0]["value"],
        events=tuple(r["value"] for r in records[1:-1]),
        seal=records[-1]["value"],
    )


def replay_shortlist(tape, cycle_key, *, as_of):
    """Rerun existing completed-bar scans and contract planning, never account admission.

    Missing histories/inventories are explicit; no later frame or current chain is
    substituted. A/B/C can share this market stage but need their own portfolios.
    """
    tape = RecordedTape.model_validate(tape.model_dump(warnings=False))
    from app.options.scope_market_tape import require_legacy_comparison

    require_legacy_comparison((tape,))
    event = next(
        (e for e in tape.available(as_of) if e.kind == "CYCLE" and e.cycle_key == cycle_key), None
    )
    if event is None:
        raise ValueError("Recorded cycle not available")
    h = tape.header
    histories = {x.symbol: x for x in event.frame.histories}
    inventories = {x.symbol: x for x in event.frame.inventories}
    window = XNYSCalendar().current_window(event.recorded_at)
    scans, plans, missing = [], [], []
    for symbol in h.setup.symbols:
        if symbol not in histories:
            missing.append(symbol + ":HISTORY_MISSING")
            continue
        scan = scan_degen(histories[symbol], h.setup, window, now=event.recorded_at)
        scans.append(scan)
        if symbol not in inventories:
            missing.append(symbol + ":INVENTORY_MISSING")
            continue
        plans.append(
            plan_contract_reads(
                scan, inventories[symbol], h.selection, h.limits, now=event.recorded_at
            )
        )
    if h.swing is not None:
        added_scans, added_plans, blockers = _replay_swing(tape, event, histories, scans)
        missing.extend(blockers)
        if h.swing.family_priority[0] == "SWING":
            scans, plans = added_scans + scans, added_plans + plans
        else:
            scans, plans = scans + added_scans, plans + added_plans
        if blockers:
            plans = []
    return {
        "cycle_key": cycle_key,
        "frame_hash": fingerprint(event.frame),
        "recorded_at": event.recorded_at.isoformat(),
        "scans": [s.model_dump(mode="json") for s in scans],
        "plans": [p.model_dump(mode="json") for p in plans],
        "missing": missing,
        "execution_authority": False,
        "live_enabled": False,
    }


def _replay_swing(tape, event, histories, scans):
    """Rebuild first-valid locks only from the visible cycle prefix, without an owner."""
    if tape.header.swing.family_batch is not None:
        from app.options.swing_batch import replay_batches

        return replay_batches(tape, event, histories, scans)
    h, calendar = tape.header, XNYSCalendar()
    locks, terminals, locked_seeds = {}, {}, {}

    def observe_quote(seed, previous):
        if h.swing.unfilled_lifecycle not in ("observed-invalidation-v2", "observed-lifecycle-v3"):
            return
        from app.options.swing_lifecycle import quote_terminal

        quotes = [q for q in previous.frame.underlyings if q.symbol == seed.history.symbol]
        if len(quotes) == 1:
            terminal = quote_terminal(
                seed, h.swing, h.limits, calendar, quotes[0], previous.recorded_at
            )
            if terminal is not None:
                terminals.setdefault(fingerprint(seed), terminal)

    for previous in tape.events:
        if previous.sequence > event.sequence:
            break
        for seed in locked_seeds.values():
            observe_quote(seed, previous)
        for item in previous.frame.swing:
            seed = item.seed
            if (
                h.swing.unfilled_lifecycle is None or seed.created_at <= previous.recorded_at
            ) and not seed_issues(seed, h.swing, calendar, h.setup.symbols):
                locks.setdefault((seed.target_session, seed.history.symbol), fingerprint(seed))
                if locks[(seed.target_session, seed.history.symbol)] == fingerprint(seed):
                    locked_seeds.setdefault(fingerprint(seed), seed)
                    observe_quote(seed, previous)
                if h.swing.unfilled_lifecycle is not None and previous.kind == "CYCLE":
                    histories_at = {x.symbol: x for x in previous.frame.histories}
                    history = histories_at.get(seed.history.symbol)
                    if history is not None and locks[
                        (seed.target_session, seed.history.symbol)
                    ] == fingerprint(seed):
                        intraday = scan_degen(
                            history,
                            h.setup,
                            calendar.current_window(previous.recorded_at),
                            now=previous.recorded_at,
                        )
                        sampled = scan_swing(
                            item,
                            h.swing,
                            intraday,
                            history,
                            calendar,
                            h.setup.symbols,
                            now=previous.recorded_at,
                            receive_lag=h.limits.max_receive_lag_seconds,
                        )
                        terminal = sampled.terminal
                        if terminal is not None:
                            terminals.setdefault(fingerprint(seed), terminal)
    items = {s.seed.history.symbol: s for s in event.frame.swing}
    added_scans, added_plans, missing = [], [], []
    for intraday in scans:
        item = items.get(intraday.symbol)
        if item is None:
            missing.append(intraday.symbol + ":EXACT_SWING_SEED_COVERAGE_REQUIRED")
            continue
        seed = item.seed
        locked = locks.get((seed.target_session, seed.history.symbol))
        if locked is not None and locked != fingerprint(seed):
            missing.append(intraday.symbol + ":SWING_SEED_LOCK_CONFLICT")
            continue
        scan = scan_swing(
            item,
            h.swing,
            intraday,
            histories[intraday.symbol],
            calendar,
            h.setup.symbols,
            now=event.recorded_at,
            receive_lag=h.limits.max_receive_lag_seconds,
        )
        if h.swing.unfilled_lifecycle is not None:
            from app.options.swing_lifecycle import apply_terminal

            scan = apply_terminal(scan, terminals.get(fingerprint(seed)))
        added_scans.append(scan)
        added_plans.append(
            plan_swing_reads(scan, item, h.selection, h.limits, now=event.recorded_at)
        )
    # The joint native cycle also blocks Degen planning on missing/conflicting locks.
    # Retain scans as diagnostics, but never present a usable partial-family plan.
    if missing:
        return added_scans, [], missing
    return added_scans, added_plans, missing


def validate_tape_series(values):
    """Validate a bounded series incrementally, including lazily loaded tape files."""
    tapes, size = [], 0
    for value in values:
        if len(tapes) == 60:
            raise ValueError("Tape count exceeds session capacity")
        tape = RecordedTape.model_validate(value.model_dump(warnings=False))
        if tapes:
            original = tapes[0].header.scope
            current = tape.header.scope
            if (original is None) != (current is None) or (
                original is not None and current.watch != original.watch
            ):
                raise ValueError("Scope tape series requires unchanged frozen watch enrollment")
        size += len(tape.model_dump_json().encode())
        if size > 2 * MAX_TAPE_BYTES:
            raise ValueError("Combined tape evidence capacity exceeded")
        tapes.append(tape)
    return tuple(tapes)
