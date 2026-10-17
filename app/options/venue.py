"""Dedicated durable local option venue. Scripted outcomes are not broker operations."""

import hashlib
import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext
from pathlib import Path
from urllib.parse import quote as uri_quote
from uuid import uuid4

from pydantic import Field

from app.options.accounting import apply_fill, apply_receipt
from app.options.governor import _fresh, _tick_price
from app.options.lifecycle import (
    TERMINAL,
    OptionFill,
    OptionIntent,
    OptionLedger,
    OptionObservation,
    OptionPosition,
    OptionReceipt,
    OptionVenueSnapshot,
    UnderlyingExposure,
)
from app.options.models import Count, Money, OptionLimits, OptionQuote, OptionRecord


def private_path(path):
    path = Path(path).expanduser().absolute()
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("A private owned regular fixture file is required")
    return path


class VenueState(OptionRecord):
    cash: Money
    settled_cash: Money
    position: OptionPosition | None = None
    orders: tuple[OptionObservation, ...] = Field(default=(), max_length=1000)
    receipts: tuple[OptionReceipt, ...] = Field(default=(), max_length=1000)
    underlying_exposures: tuple[UnderlyingExposure, ...] = Field(default=(), max_length=32)
    sequence: Count = 0
    submit_count: Count = 0


class DurableOptionVenue:
    def __init__(self, path, *, limits: OptionLimits | None = None, capital=None, fault="NONE"):
        self.path = Path(path).expanduser().absolute()
        self.fault = fault
        if capital is not None:
            if limits is None:
                raise ValueError("Explicit frozen option policy required")
            limits = OptionLimits.model_validate(limits.model_dump(warnings=False))
            initial = OptionLedger(cash=capital, high_watermark=capital)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with self._db(write=True) as db:
                db.execute(
                    "CREATE TABLE option_fixture_control (id INTEGER PRIMARY KEY CHECK(id=1),meta TEXT NOT NULL,state TEXT NOT NULL)"
                )
                meta = {
                    "schema": "durable-option-fixture-v1",
                    "venue_id": uuid4().hex,
                    "initial_capital": str(initial.cash),
                    "limits": limits.model_dump(mode="json"),
                }
                state = VenueState(cash=initial.cash, settled_cash=initial.cash)
                db.execute(
                    "INSERT INTO option_fixture_control VALUES(1,?,?)",
                    (json.dumps(meta, sort_keys=True), state.model_dump_json()),
                )
        with self._db() as db:
            meta, _ = self._load(db)
        self.venue_id = meta["venue_id"]
        self.limits = OptionLimits.model_validate(meta["limits"])
        self.initial_capital = Decimal(meta["initial_capital"])
        self.account_id, self.population_id = self.limits.account_id, self.limits.population_id

    @contextmanager
    def _db(self, write=False):
        private_path(self.path)
        db = sqlite3.connect(
            "file:" + uri_quote(str(self.path)) + ("?mode=rw" if write else "?mode=ro"),
            uri=True,
            timeout=1,
            isolation_level=None,
        )
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            with localcontext(Context(prec=192)):
                yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _load(db):
        if {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {
            "option_fixture_control"
        }:
            raise ValueError("Not a dedicated option fixture")
        row = db.execute("SELECT meta,state FROM option_fixture_control WHERE id=1").fetchone()
        meta = json.loads(row[0])
        if meta["schema"] != "durable-option-fixture-v1":
            raise ValueError("Wrong option fixture schema")
        return meta, VenueState.model_validate_json(row[1])

    def _mutate(self, operation, *, deadline=None, parent_pid=None):
        with self._db(write=True) as db:
            meta, state = self._load(db)
            if (
                meta["venue_id"] != self.venue_id
                or OptionLimits.model_validate(meta["limits"]) != self.limits
            ):
                raise ValueError("Option fixture binding changed")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Fixture admission lease expired")
            if parent_pid is not None and os.getppid() != parent_pid:
                raise OSError("Fixture parent lost ownership")
            updated, result = operation(state)
            updated = VenueState.model_validate(updated.model_dump(warnings=False))
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Fixture admission lease expired before commit")
            if parent_pid is not None and os.getppid() != parent_pid:
                raise OSError("Fixture parent lost ownership before commit")
            db.execute(
                "UPDATE option_fixture_control SET state=? WHERE id=1", (updated.model_dump_json(),)
            )
            return result

    def _accept(self, intent, now, deadline, parent_pid):
        intent = OptionIntent.model_validate(intent.model_dump(warnings=False))

        def accept(state):
            if any(o.client_id == intent.client_id for o in state.orders):
                raise ValueError("An attempted option order cannot replay")
            if any(o.status not in TERMINAL for o in state.orders) or state.underlying_exposures:
                raise ValueError("Fixture already has working/unsupported exposure")
            if not intent.prepared_at <= now < intent.approval_expires_at:
                raise ValueError("Option approval expired")
            if intent.side == "BUY":
                if (
                    state.position is not None
                    or intent.approved_full_premium_loss > state.settled_cash
                ):
                    raise ValueError("Duplicate position or unfunded premium")
            elif (
                state.position is None
                or state.position.contract != intent.instrument.contract
                or intent.quantity > state.position.quantity
            ):
                raise ValueError("An opening short or oversell is forbidden")
            order = OptionObservation(
                order_id="option-fixture-" + uuid4().hex,
                client_id=intent.client_id,
                instrument=intent.instrument,
                side=intent.side,
                quantity=intent.quantity,
                limit_price=intent.limit_price,
                status="OPEN",
                filled_quantity=0,
                updated_at=now,
            )
            return state.model_copy(
                update={"orders": (*state.orders, order), "submit_count": state.submit_count + 1}
            ), order.order_id

        return self._mutate(accept, deadline=deadline, parent_pid=parent_pid)

    def fill(self, intent: OptionIntent, quantity: int, quote: OptionQuote, at, *, fill_id):
        intent = OptionIntent.model_validate(intent.model_dump(warnings=False))
        quote = OptionQuote.model_validate(quote.model_dump(warnings=False))

        def fill(state):
            order = next(o for o in state.orders if o.client_id == intent.client_id)
            if (
                order.status in TERMINAL
                or order.instrument != intent.instrument
                or order.side != intent.side
                or order.quantity != intent.quantity
                or order.limit_price != intent.limit_price
            ):
                raise ValueError("Invalid fixture fill lineage")
            if not order.updated_at <= at < intent.order_expires_at:
                raise ValueError("Fill lies outside ordered DAY lifetime")
            if (
                quote.instrument != intent.instrument
                or quote.source != self.limits.option_source
                or not quote.complete
                or quote.entitlement != "REALTIME"
                or not _fresh(
                    quote.source_at,
                    quote.received_at,
                    at,
                    self.limits.quote_max_age_seconds,
                    self.limits.max_receive_lag_seconds,
                )
            ):
                raise ValueError("An exact fresh executable quote is required")
            if (
                quote.bid is None
                or quote.bid <= 0
                or (quote.ask is not None and quote.bid > quote.ask)
            ):
                raise ValueError("Missing or crossed executable quote")
            raw, size = (
                (quote.ask, quote.ask_size) if intent.side == "BUY" else (quote.bid, quote.bid_size)
            )
            if raw is None:
                raise ValueError("Executable price unavailable")
            direction = 1 if intent.side == "BUY" else -1
            price = _tick_price(
                raw * (1 + direction * self.limits.slippage_bps / 10000),
                intent.instrument.contract,
                ROUND_CEILING if direction == 1 else ROUND_FLOOR,
            )
            if (
                price <= 0
                or (direction == 1 and price > intent.limit_price)
                or (direction == -1 and price < intent.limit_price)
            ):
                raise ValueError("Executable fill is outside fixed limit")
            digest = hashlib.sha256(quote.model_dump_json().encode()).hexdigest()
            consumed = sum(
                f.quantity
                for o in state.orders
                if o.side == intent.side
                for f in o.fills
                if f.quote == quote
            )
            if type(quantity) is not int or not 0 < quantity <= min(
                size - consumed, order.quantity - order.filled_quantity
            ):
                raise ValueError("Whole fill must fit remaining order and unused observed size")
            if any(f.fill_id == fill_id for o in state.orders for f in o.fills):
                raise ValueError("Duplicate fixture fill identity")
            per_order, per_contract = (
                (self.limits.entry_fee_per_order, self.limits.entry_fee_per_contract)
                if direction == 1
                else (self.limits.exit_fee_per_order, self.limits.exit_fee_per_contract)
            )
            fee = per_contract * quantity + (per_order if not order.fills else 0)
            receipt = OptionFill(
                fill_id=fill_id,
                order_id=order.order_id,
                sequence=state.sequence + 1,
                quantity=quantity,
                price=price,
                fee=fee,
                occurred_at=at,
                quote_hash=digest,
                quote=quote,
            )
            ledger = apply_fill(
                OptionLedger(
                    cash=state.cash,
                    settled_cash=state.settled_cash,
                    position=state.position,
                    high_watermark=self.initial_capital,
                ),
                intent,
                receipt,
            )
            total = order.filled_quantity + quantity
            updated = order.model_copy(
                update={
                    "fills": (*order.fills, receipt),
                    "filled_quantity": total,
                    "status": "FILLED" if total == order.quantity else "PARTIAL",
                    "updated_at": at,
                }
            )
            return state.model_copy(
                update={
                    "cash": ledger.cash,
                    "settled_cash": ledger.settled_cash,
                    "position": ledger.position,
                    "sequence": receipt.sequence,
                    "orders": tuple(
                        updated if o.client_id == order.client_id else o for o in state.orders
                    ),
                }
            ), receipt

        return self._mutate(fill)

    def record_terminal(self, client_id, status, at):
        """Script an authoritative fake outcome. This is not an order-cancel adapter."""
        if status not in {"CANCELED", "REJECTED", "EXPIRED"}:
            raise ValueError("Invalid scripted terminal outcome")

        def terminal(state):
            old = next(o for o in state.orders if o.client_id == client_id)
            if (
                old.status in TERMINAL
                or at < old.updated_at
                or (status == "REJECTED" and old.fills)
            ):
                raise ValueError("Terminal history cannot regress")
            updated = old.model_copy(update={"status": status, "updated_at": at})
            return state.model_copy(
                update={
                    "orders": tuple(
                        updated if o.client_id == client_id else o for o in state.orders
                    )
                }
            ), None

        return self._mutate(terminal)

    def record_receipt(self, receipt):
        receipt = OptionReceipt.model_validate(receipt.model_dump(warnings=False))

        def record(state):
            if receipt.sequence != state.sequence + 1 or any(
                r.receipt_id == receipt.receipt_id for r in state.receipts
            ):
                raise ValueError("Receipt sequence/identity conflict")
            if any(o.status not in TERMINAL for o in state.orders):
                raise ValueError("Contract/funds receipts require complete terminal order history")
            updates = {"sequence": receipt.sequence, "receipts": (*state.receipts, receipt)}
            if receipt.kind == "PHYSICAL_EXERCISE":
                p = state.position
                if (
                    p is None
                    or receipt.contract != p.contract
                    or receipt.quantity != p.quantity
                    or p.contract.settlement != "PHYSICAL"
                    or receipt.occurred_at < p.contract.expires_at
                ):
                    raise ValueError("Invalid scripted physical exposure receipt")
                shares = (
                    receipt.quantity
                    * p.contract.multiplier
                    * (1 if p.contract.right == "CALL" else -1)
                )
                delta = -shares * p.contract.strike
                if receipt.cash_change != delta:
                    raise ValueError("Physical exercise cash terms conflict")
                updates.update(
                    cash=state.cash + delta,
                    settled_cash=state.settled_cash + delta,
                    position=None,
                    underlying_exposures=(
                        UnderlyingExposure(symbol=p.contract.underlying, quantity=Decimal(shares)),
                    ),
                )
            else:
                ledger = apply_receipt(
                    OptionLedger(
                        cash=state.cash,
                        settled_cash=state.settled_cash,
                        position=state.position,
                        high_watermark=self.initial_capital,
                    ),
                    receipt,
                )
                updates.update(
                    cash=ledger.cash, settled_cash=ledger.settled_cash, position=ledger.position
                )
            return state.model_copy(update=updates), None

        return self._mutate(record)

    def snapshot(self, at):
        with self._db() as db:
            meta, state = self._load(db)
        if (
            meta["venue_id"] != self.venue_id
            or OptionLimits.model_validate(meta["limits"]) != self.limits
        ):
            raise ValueError("Option venue identity changed")
        payload = state.model_dump_json() + at.isoformat()
        return OptionVenueSnapshot(
            venue_id=self.venue_id,
            account_id=self.account_id,
            population_id=self.population_id,
            snapshot_id=hashlib.sha256(payload.encode()).hexdigest(),
            captured_at=at,
            cash=state.cash,
            settled_cash=state.settled_cash,
            position=state.position,
            orders=state.orders,
            receipts=state.receipts,
            underlying_exposures=state.underlying_exposures,
        )

    @property
    def submit_count(self):
        with self._db() as db:
            return self._load(db)[1].submit_count
