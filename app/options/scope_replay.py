"""Create-only Scope research lifecycle replay. No orders, model calls or trading results."""

import argparse
import json
import os
import sqlite3
import stat
import sys
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution, fingerprint
from app.options.lifecycle import OptionExecutionPolicy
from app.options.models import Name, OptionLimits, OptionRecord, UnderlyingQuote
from app.options.observer import OptionObserver
from app.options.replay import _save
from app.options.scope import ScopePreflightInput
from app.options.scope_context import ScopeContextInput
from app.options.scope_watch import ScopeWatchBook, ScopeWatchChoice, ScopeWatchPolicy
from app.options.venue import DurableOptionVenue

MAX_REQUEST_BYTES = 16 * 1024 * 1024


class ScopeReplayStep(OptionRecord):
    key: Name
    kind: Literal["CALL", "OBSERVE_ARMING", "REVIEW_ADMISSION", "ADVANCE", "NEUTRALIZE"]
    at: datetime
    play_key: Name
    choice: ScopeWatchChoice | None = None
    frame: ScopePreflightInput | None = None
    context: ScopeContextInput | None = None
    underlying: UnderlyingQuote | None = None

    @model_validator(mode="after")
    def action_inputs(self):
        if self.kind == "CALL":
            if self.key != self.play_key or any(
                v is None for v in (self.choice, self.frame, self.context)
            ):
                raise ValueError("CALL requires its own play key, choice, frame and context")
        elif self.choice is not None:
            raise ValueError("Only CALL selects a locked choice")
        if self.kind in {"ADVANCE", "NEUTRALIZE"} and self.context is not None:
            raise ValueError("Price advance/reset accepts no context override")
        if self.kind == "NEUTRALIZE" and self.frame is None:
            raise ValueError("Neutral reset requires completed evidence")
        if self.kind != "REVIEW_ADMISSION" and self.underlying is not None:
            raise ValueError("Only owned admission accepts an underlying quote")

        # Future validity windows/contract expiry are permitted, future received data is not.
        def observed(value):
            if isinstance(value, dict):
                if "received_at" in value and value["received_at"] > self.at:
                    raise ValueError("Scope replay cannot use evidence received after its step")
                for item in value.values():
                    observed(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    observed(item)

        observed(self.model_dump())
        return self


class ScopeReplayRequest(OptionRecord):
    version: Literal["scope-research-replay-v1"] = "scope-research-replay-v1"
    limits: OptionLimits
    execution: OptionExecutionPolicy
    watch: ScopeWatchPolicy
    started_at: datetime
    steps: tuple[ScopeReplayStep, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def frozen_sequence(self):
        times = [self.started_at, *(s.at for s in self.steps)]
        p = self.watch.context.structure.preflight
        if (
            any(a > b for a, b in pairwise(times))
            or len({s.key for s in self.steps}) != len(self.steps)
            or "SPX" not in self.limits.allowed_underlyings
            or p.provider != self.limits.provider
            or p.quote_source != self.limits.option_source
        ):
            raise ValueError("Ordered unique Scope actions and matching owner bindings required")
        return self


def _revision(engine):
    with engine.journal.read() as db:
        return engine.journal.revision(db)


def _perform(book, step, revision):
    common = {"now": step.at, "expected_revision": revision}
    if step.kind == "CALL":
        return book.call(step.key, step.choice, step.frame, step.context, **common)
    if step.kind == "NEUTRALIZE":
        return book.neutralize(step.key, step.play_key, step.frame, **common)
    if step.kind == "ADVANCE":
        return book.advance(step.key, step.play_key, frame=step.frame, **common)
    common.update(frame=step.frame, context=step.context)
    if step.kind == "REVIEW_ADMISSION":
        return book.review_admission(step.key, step.play_key, underlying=step.underlying, **common)
    return book.observe_arming(step.key, step.play_key, **common)


def run_scope_replay(request, directory):
    """Use only built-in isolated PAPER ownership; callers cannot inject a venue or account."""
    request = ScopeReplayRequest.model_validate(request.model_dump(warnings=False))
    raw = request.model_dump(mode="json")
    if len(json.dumps(raw).encode()) > MAX_REQUEST_BYTES:
        raise ValueError("Bounded Scope replay request required")
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute new Scope replay directory required")
    directory.mkdir(mode=0o700)  # Existing, interrupted and symlink destinations are never resumed.
    digest = fingerprint(request)
    _save(directory / "inputs.json", {"request_hash": digest, "request": raw})
    (directory / "actions").mkdir(mode=0o700)
    try:
        venue = DurableOptionVenue(
            directory / "venue.db", limits=request.limits, capital=request.execution.capital
        )
        with OptionExecution.open(
            directory / "options.db",
            request.limits,
            request.execution,
            venue,
            now=request.started_at,
            create=True,
        ) as engine:
            if not engine.reconcile(venue.snapshot(request.started_at), now=request.started_at)[
                "reconciled"
            ]:
                raise ValueError("Scope replay initial reconciliation failed")
            engine.assess(None, None, now=request.started_at)
            book = ScopeWatchBook(engine, request.watch, now=request.started_at, create=True)
            actions = []
            for index, step in enumerate(request.steps):
                if not engine.reconcile(venue.snapshot(step.at), now=step.at)["reconciled"]:
                    raise ValueError("Scope replay step reconciliation failed")
                engine.assess(None, None, now=step.at)
                before = _revision(engine)
                receipt, reason = None, None
                try:
                    receipt = _perform(book, step, before)
                except ExecutionBlocked as exc:
                    reason = str(exc)
                    if _revision(engine) != before:
                        raise ValueError("Rejected Scope action changed its journal") from exc
                action = {
                    "index": index,
                    "key": step.key,
                    "kind": step.kind,
                    "at": step.at.isoformat(),
                    "play_key": step.play_key,
                    "step_hash": fingerprint(step),
                    "expected_revision": before,
                    "status": "RECORDED" if receipt is not None else "REJECTED",
                    "reason": reason,
                    "receipt_hash": fingerprint(receipt) if receipt else None,
                    "receipt": receipt,
                    "execution_authority": False,
                    "live_enabled": False,
                }
                filename = f"actions/{index:03d}.json"
                _save(directory / filename, action)
                actions.append(
                    {k: v for k, v in action.items() if k != "receipt"} | {"artifact": filename}
                )
            now = request.steps[-1].at
            with engine.journal.read() as db:
                for table in (
                    "execution_orders",
                    "execution_fills",
                    "execution_model_calls",
                    "execution_option_decisions",
                ):
                    if db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                        raise ValueError("Research replay produced native trading activity")
            view = OptionObserver(
                engine.journal.path, request.limits.population_id, clock=lambda: now
            ).report()
            if view["status"] != "OK":
                raise ValueError("Scope replay stored evidence is unavailable")
            report = {
                "version": request.version,
                "status": "COMPLETE_RESEARCH_REPLAY",
                "evidence_kind": "LOCAL_FIXTURE",
                "economic_conclusion": "NOT_EVALUATED",
                "data_cost": None,
                "host_cost": None,
                "net_return": None,
                "request_hash": digest,
                "population_id": request.limits.population_id,
                "started_at": request.started_at.isoformat(),
                "completed_at": now.isoformat(),
                "steps": actions,
                "recorded_actions": sum(a["status"] == "RECORDED" for a in actions),
                "rejected_actions": sum(a["status"] == "REJECTED" for a in actions),
                "scope": view["scope"],
                "economics": view["economics"],
                "model": view["model"],
                "orders": view["orders"],
                "fills": view["fills"],
                "native_revision": _revision(engine),
                "execution_authority": False,
                "live_enabled": False,
            }
        _save(directory / "report.json", report)
        return report
    except BaseException:
        _save(
            directory / "interrupted.json",
            {
                "status": "INCOMPLETE_RESEARCH_REPLAY",
                "request_hash": digest,
                "execution_authority": False,
                "live_enabled": False,
            },
        )
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="Private frozen Scope research JSON")
    parser.add_argument("--output", required=True, help="Absolute new private output directory")
    args = parser.parse_args(argv)
    try:
        fd = os.open(args.request, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= MAX_REQUEST_BYTES
            ):
                raise ValueError("Private bounded Scope replay request required")
            raw = stream.read(MAX_REQUEST_BYTES + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > MAX_REQUEST_BYTES or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Scope replay request changed")
        report = run_scope_replay(ScopeReplayRequest.model_validate_json(raw), args.output)
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        ArithmeticError,
        TimeoutError,
        ExecutionBlocked,
    ):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "SCOPE_REPLAY_UNAVAILABLE",
                    "execution_authority": False,
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "request_hash",
                    "recorded_actions",
                    "rejected_actions",
                    "economic_conclusion",
                    "execution_authority",
                    "live_enabled",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
