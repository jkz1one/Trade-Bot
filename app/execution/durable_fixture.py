"""A private durable fake venue. This module has no brokerage transport."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from app.execution.fixture import LocalFixtureVenue
from app.execution.models import Contract, Observation, VenuePosition

FixtureFault = Literal[
    "NONE",
    "STALL_BEFORE_ACCEPT",
    "STALL_AFTER_ACCEPT",
    "IGNORE_TERM_AFTER_ACCEPT",
    "CRASH_AFTER_ACCEPT",
    "LOST_ACK",
    "INVALID_ACK",
    "OVERSIZED_ACK",
    "STALL_READ",
]


class FixtureState(Contract):
    # Each transaction revalidates serialized Decimal state, including all order history.
    cash: Decimal = Field(ge=0)
    position: VenuePosition | None = None
    orders: list[Observation] = Field(default_factory=list)
    submit_count: int = Field(default=0, ge=0)


class DurableFixtureVenue:
    """Open an existing fake venue, or exclusively create one with explicit capital."""

    def __init__(
        self, path, *, capital=None, account_id="execution-rehearsal", fault: FixtureFault = "NONE"
    ):
        self.path = Path(path).expanduser().resolve()
        self.fault = fault
        if capital is not None:
            state = FixtureState(cash=capital)
            if not account_id.strip() or len(account_id) > 128:
                raise ValueError("A bounded fixture account identity is required")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Never adopt or overwrite any existing engine/broker/experiment database.
            with self.path.open("xb"):
                self.path.chmod(0o600)
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "CREATE TABLE fixture_control(id INTEGER PRIMARY KEY CHECK(id=1), meta TEXT NOT NULL, state TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO fixture_control VALUES(1,?,?)",
                    (
                        json.dumps(
                            {
                                "schema": "local-fixture-venue-v1",
                                "venue_id": uuid4().hex,
                                "account_id": account_id,
                                "initial_capital": str(state.cash),
                            }
                        ),
                        state.model_dump_json(),
                    ),
                )
        with self._read() as db:
            meta, _ = self._load(db)
            self.account_id = meta["account_id"]
            self.venue_id = meta["venue_id"]

    @contextmanager
    def _read(self):
        from urllib.parse import quote

        db = sqlite3.connect("file:" + quote(str(self.path)) + "?mode=ro", uri=True, timeout=1)
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _load(db):
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != {"fixture_control"}:
            raise ValueError("Not a dedicated local fixture venue")
        row = db.execute("SELECT meta,state FROM fixture_control WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Missing fixture state")
        meta = json.loads(row[0])
        if meta.get("schema") != "local-fixture-venue-v1":
            raise ValueError("Not a local fixture venue")
        state = FixtureState.model_validate_json(row[1])
        venue = LocalFixtureVenue(state.cash, account_id=meta["account_id"])
        venue.position = state.position
        venue.orders = {o.client_id: o for o in state.orders}
        if len(venue.orders) != len(state.orders):
            raise ValueError("Duplicate fixture identities")
        venue.submit_count = state.submit_count
        return meta, venue

    def _mutate(self, method, *args, _deadline=None, _parent_pid=None, **kwargs):
        # Read first; SQLite must never create a missing/replaced path during mutation.
        from urllib.parse import quote

        with sqlite3.connect(
            "file:" + quote(str(self.path)) + "?mode=rw", uri=True, timeout=1
        ) as db:
            db.execute("BEGIN IMMEDIATE")
            meta, venue = self._load(db)
            if meta["venue_id"] != self.venue_id or meta["account_id"] != self.account_id:
                raise ValueError("Fixture venue identity changed")
            if _deadline is not None and time.monotonic() >= _deadline:
                raise TimeoutError("Fixture admission lease expired")
            if _parent_pid is not None and os.getppid() != _parent_pid:
                raise OSError("Fixture parent no longer owns this attempt")
            result = getattr(venue, method)(*args, **kwargs)
            state = FixtureState(
                cash=venue.cash,
                position=venue.position,
                orders=list(venue.orders.values()),
                submit_count=venue.submit_count,
            )
            db.execute("UPDATE fixture_control SET state=? WHERE id=1", (state.model_dump_json(),))
            return result

    def _accept(self, intent, now, deadline_monotonic, parent_pid):
        return self._mutate(
            "accept", intent, now, _deadline=deadline_monotonic, _parent_pid=parent_pid
        )

    def fill(self, client_id, quantity, price, at, **kwargs):
        return self._mutate("fill", client_id, quantity, price, at, **kwargs)

    def terminal(self, client_id, status, at):
        # A scripted local outcome, never a broker cancellation operation.
        return self._mutate("terminal", client_id, status, at)

    def snapshot(self, at):
        with self._read() as db:
            meta, venue = self._load(db)
            if meta["venue_id"] != self.venue_id or meta["account_id"] != self.account_id:
                raise ValueError("Fixture venue identity changed")
            return venue.snapshot(at)

    @property
    def submit_count(self):
        with self._read() as db:
            return self._load(db)[1].submit_count
