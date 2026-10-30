"""Dedicated durable local option venue. Scripted outcomes are not broker operations."""

from app.options.models import parse_underlying
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

from pydantic import Field, model_validator

from app.options.models import paper_market_evidence
from app.mixed.stock_models import StockLimits, StockObservation, StockPosition
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
from app.options.models import (
    Count,
    Money,
    OptionLimits,
    OptionQuote,
    OptionRecord,
    UnderlyingObservation,
)


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
    stock_position: StockPosition | None = Field(default=None, exclude_if=lambda v: v is None)
    stock_orders: tuple[StockObservation, ...] = Field(
        default=(), max_length=1000, exclude_if=lambda v: not v
    )
    orders: tuple[OptionObservation, ...] = Field(default=(), max_length=1000)
    receipts: tuple[OptionReceipt, ...] = Field(default=(), max_length=1000)
    underlying_exposures: tuple[UnderlyingExposure, ...] = Field(default=(), max_length=32)
    sequence: Count = 0
    submit_count: Count = 0

    @model_validator(mode="after")
    def exclusive_position(self):
        if self.position is not None and self.stock_position is not None:
            raise ValueError("A venue has one position across instrument types")
        return self


class DurableOptionVenue:
    def __init__(
        self,
        path,
        *,
        limits: OptionLimits | None = None,
        capital=None,
        fault="NONE",
        stock_limits=None,
        portfolio_policy=None,
    ):
        self.path = Path(path).expanduser().absolute()
        self.fault = fault
        stock_limits = (
            StockLimits.model_validate(stock_limits.model_dump(warnings=False))
            if stock_limits is not None
            else None
        )
        if portfolio_policy is not None:
            from app.mixed.portfolio_accounting import PortfolioPolicy

            portfolio_policy = PortfolioPolicy.model_validate(portfolio_policy.model_dump())
            if capital is not None and (
                portfolio_policy.options != limits
                or portfolio_policy.stocks != stock_limits
                or portfolio_policy.capital != Decimal(capital)
            ):
                raise ValueError("Exact shared portfolio venue policy required")
        if capital is not None:
            if limits is None:
                raise ValueError("Explicit frozen option policy required")
            limits = OptionLimits.model_validate(limits.model_dump(warnings=False))
            if stock_limits is not None and stock_limits.provider != limits.provider:
                raise ValueError("One frozen provider across stock/options required")
            initial = OptionLedger(cash=capital, high_watermark=capital)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with self._db(write=True) as db:
                db.execute(
                    "CREATE TABLE option_fixture_control (id INTEGER PRIMARY KEY CHECK(id=1),meta TEXT NOT NULL,state TEXT NOT NULL)"
                )
                meta = {
                    "schema": "durable-mixed-fixture-v1"
                    if stock_limits is not None
                    else "durable-option-fixture-v1",
                    "venue_id": uuid4().hex,
                    "initial_capital": str(initial.cash),
                    "limits": limits.model_dump(mode="json"),
                }
                if stock_limits is not None:
                    meta["stock_limits"] = stock_limits.model_dump(mode="json")
                state_type = VenueState
                if portfolio_policy is not None:
                    from app.mixed.portfolio_venue import PortfolioVenueState

                    state_type = PortfolioVenueState
                    meta["schema"] = "durable-portfolio-fixture-v2"
                    meta["portfolio_policy"] = portfolio_policy.model_dump(mode="json")
                state = state_type(cash=initial.cash, settled_cash=initial.cash)
                db.execute(
                    "INSERT INTO option_fixture_control VALUES(1,?,?)",
                    (json.dumps(meta, sort_keys=True), state.model_dump_json()),
                )
        with self._db() as db:
            meta, _ = self._load(db)
        from app.mixed.portfolio_accounting import PortfolioPolicy

        self.portfolio_policy = (
            PortfolioPolicy.model_validate(meta["portfolio_policy"])
            if "portfolio_policy" in meta
            else None
        )
        if portfolio_policy is not None and portfolio_policy != self.portfolio_policy:
            raise ValueError("Portfolio venue policy mismatch")
        self.venue_id = meta["venue_id"]
        self.limits = OptionLimits.model_validate(meta["limits"])
        self.stock_limits = (
            StockLimits.model_validate(meta["stock_limits"]) if "stock_limits" in meta else None
        )
        if stock_limits is not None and stock_limits != self.stock_limits:
            raise ValueError("Stock fixture policy mismatch")
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
        if meta["schema"] != (
            "durable-portfolio-fixture-v2"
            if "portfolio_policy" in meta
            else "durable-mixed-fixture-v1"
            if "stock_limits" in meta
            else "durable-option-fixture-v1"
        ):
            raise ValueError("Wrong option fixture schema")
        state_type = VenueState
        if "portfolio_policy" in meta:
            from app.mixed.portfolio_venue import PortfolioPolicy, PortfolioVenueState

            policy = PortfolioPolicy.model_validate(meta["portfolio_policy"])
            if (
                policy.options.model_dump(mode="json") != meta["limits"]
                or policy.stocks.model_dump(mode="json") != meta.get("stock_limits")
                or policy.capital != Decimal(meta["initial_capital"])
            ):
                raise ValueError("Portfolio venue enrollment changed")
            state_type = PortfolioVenueState
        state = state_type.model_validate_json(row[1])
        if "stock_limits" not in meta and (state.stock_position is not None or state.stock_orders):
            raise ValueError("Stock fixture inputs not enrolled")
        if "stock_limits" in meta:
            from app.mixed.venue import validate_state

            if (
                StockLimits.model_validate(meta["stock_limits"]).provider
                != OptionLimits.model_validate(meta["limits"]).provider
            ):
                raise ValueError("Mixed fixture provider binding changed")
            validate_state(state)
        return meta, state

    def _mutate(self, operation, *, deadline=None, parent_pid=None, intent=None, identity=None):
        with self._db(write=True) as db:
            meta, state = self._load(db)
            if (
                meta["venue_id"] != self.venue_id
                or OptionLimits.model_validate(meta["limits"]) != self.limits
                or (
                    StockLimits.model_validate(meta["stock_limits"])
                    if "stock_limits" in meta
                    else None
                )
                != self.stock_limits
            ):
                raise ValueError("Option fixture binding changed")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Fixture admission lease expired")
            if parent_pid is not None and os.getppid() != parent_pid:
                raise OSError("Fixture parent lost ownership")
            prior = state
            if self.portfolio_policy is not None:
                from app.mixed.portfolio_venue import merge, play_id, view

                if meta.get("portfolio_policy") != self.portfolio_policy.model_dump(mode="json"):
                    raise ValueError("Portfolio venue policy changed")
                if intent is not None:
                    identity = play_id(intent)
                state = view(state, identity)
            updated, result = operation(state)
            if self.portfolio_policy is not None:
                updated = merge(prior, updated, identity)
                if intent is not None and any(
                    o.client_id == intent.client_id
                    for o in (*updated.orders, *updated.stock_orders)
                ):
                    intents = dict(updated.intents)
                    if intent.client_id in intents and intents[intent.client_id] != intent:
                        raise ValueError("Portfolio original intent changed")
                    intents[intent.client_id] = intent
                    updated = updated.model_copy(update={"intents": intents})
            updated = type(prior).model_validate(updated.model_dump(warnings=False))
            if self.portfolio_policy is not None:
                from app.mixed.portfolio_venue import validate

                at = max(
                    (o.updated_at for o in (*updated.orders, *updated.stock_orders)), default=None
                )
                at = (
                    max((r.occurred_at for r in updated.receipts), default=at)
                    if at is None
                    else max([at, *(r.occurred_at for r in updated.receipts)])
                )
                if at is not None:
                    validate(self, updated, at)
            if self.stock_limits is not None:
                from app.mixed.venue import validate_state

                validate_state(updated)
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
            if self.stock_limits is not None:
                from app.mixed.venue import _clock

                _clock(state, now)
            if any(o.client_id == intent.client_id for o in (*state.orders, *state.stock_orders)):
                raise ValueError("An attempted option order cannot replay")
            if (
                self.portfolio_policy is None
                and any(o.status not in TERMINAL for o in (*state.orders, *state.stock_orders))
            ) or state.underlying_exposures:
                raise ValueError("Fixture already has working/unsupported exposure")
            if self.portfolio_policy is not None:
                from app.mixed.portfolio_venue import accepting

                accepting(self, state, intent, now)
            if not intent.prepared_at <= now < intent.approval_expires_at:
                raise ValueError("Option approval expired")
            if intent.side == "BUY":
                if (
                    state.position is not None
                    or state.stock_position is not None
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

        return self._mutate(accept, deadline=deadline, parent_pid=parent_pid, intent=intent)

    def fill(
        self,
        intent: OptionIntent,
        quantity: int,
        quote: OptionQuote,
        at,
        *,
        fill_id,
        underlying=None,
    ):
        intent = OptionIntent.model_validate(intent.model_dump(warnings=False))
        quote = OptionQuote.model_validate(quote.model_dump(warnings=False))
        if underlying is not None:
            from app.options.fill_evidence import validate_underlying

            underlying = parse_underlying(underlying.model_dump(warnings=False))
            validate_underlying(self.limits, intent, quote, underlying, at)

        def fill(state):
            if self.stock_limits is not None:
                from app.mixed.venue import _clock

                _clock(state, at)
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
                or not paper_market_evidence(quote)
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
            if any(
                f.fill_id == fill_id for o in (*state.orders, *state.stock_orders) for f in o.fills
            ):
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
                underlying=underlying,
            )
            if self.portfolio_policy is not None:
                from app.mixed.portfolio_accounting import check_option_source_size

                used = {}
                for previous in state.orders:
                    for old in previous.fills:
                        check_option_source_size(state.intents[previous.client_id], old, used)
                check_option_source_size(intent, receipt, used)
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

        return self._mutate(fill, intent=intent)

    def record_terminal(self, client_id, status, at):
        """Script an authoritative fake outcome. This is not an order-cancel adapter."""
        if status not in {"CANCELED", "REJECTED", "EXPIRED"}:
            raise ValueError("Invalid scripted terminal outcome")

        def terminal(state):
            if self.stock_limits is not None:
                from app.mixed.venue import _clock

                _clock(state, at)
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

    def record_receipt(self, receipt, *, play_id=None):
        receipt = OptionReceipt.model_validate(receipt.model_dump(warnings=False))

        if self.portfolio_policy is None and play_id is not None:
            raise ValueError("Legacy settlement cannot bind a portfolio play")
        if self.portfolio_policy is not None and (receipt.kind != "FUNDS_SETTLED") != (
            play_id is not None
        ):
            raise ValueError("Contract settlement requires exact play identity")

        def record(state):
            if self.stock_limits is not None:
                from app.mixed.venue import _clock

                _clock(state, receipt.occurred_at)
            if receipt.sequence != state.sequence + 1 or any(
                r.receipt_id == receipt.receipt_id for r in state.receipts
            ):
                raise ValueError("Receipt sequence/identity conflict")
            if any(
                o.status not in TERMINAL
                and (
                    play_id is None
                    or (
                        state.intents[o.client_id].client_id
                        if state.intents[o.client_id].side == "BUY"
                        else state.intents[o.client_id].closing_entry_client_id
                    )
                    == play_id
                )
                for o in (*state.orders, *state.stock_orders)
            ):
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
            if self.portfolio_policy is not None and play_id is not None:
                updates["settlement_plays"] = {
                    **state.settlement_plays,
                    receipt.receipt_id: play_id,
                }
            return state.model_copy(update=updates), None

        return self._mutate(record, identity=play_id)

    def snapshot(self, at):
        with self._db() as db:
            meta, state = self._load(db)
        if (
            meta["venue_id"] != self.venue_id
            or OptionLimits.model_validate(meta["limits"]) != self.limits
            or (
                StockLimits.model_validate(meta["stock_limits"]) if "stock_limits" in meta else None
            )
            != self.stock_limits
        ):
            raise ValueError("Option venue identity changed")
        if self.stock_limits is not None:
            from app.mixed.venue import _clock

            _clock(state, at)
        payload = state.model_dump_json() + at.isoformat()
        snapshot_type, extra = OptionVenueSnapshot, {}
        if self.portfolio_policy is not None:
            from app.mixed.portfolio_venue import PortfolioVenueSnapshot, validate

            validate(self, state, at)
            snapshot_type = PortfolioVenueSnapshot
            extra = {
                "portfolio_policy": self.portfolio_policy,
                "positions": state.positions,
                "settlement_plays": state.settlement_plays,
            }
        return snapshot_type(
            **extra,
            venue_id=self.venue_id,
            account_id=self.account_id,
            population_id=self.population_id,
            snapshot_id=hashlib.sha256(payload.encode()).hexdigest(),
            captured_at=at,
            cash=state.cash,
            settled_cash=state.settled_cash,
            position=state.position,
            stock_position=state.stock_position,
            stock_orders=state.stock_orders,
            stock_limits=self.stock_limits,
            orders=state.orders,
            receipts=state.receipts,
            underlying_exposures=state.underlying_exposures,
        )

    @property
    def submit_count(self):
        with self._db() as db:
            return self._load(db)[1].submit_count

    def _accept_stock(self, intent, now, deadline, parent_pid):
        from app.mixed.venue import accept

        return accept(self, intent, now, deadline, parent_pid)

    def fill_stock(self, intent, quantity, quote, at, *, fill_id):
        from app.mixed.venue import fill

        return fill(self, intent, quantity, quote, at, fill_id=fill_id)

    def record_stock_terminal(self, client_id, status, at):
        from app.mixed.venue import terminal

        return terminal(self, client_id, status, at)
