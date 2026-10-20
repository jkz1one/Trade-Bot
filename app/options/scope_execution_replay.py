"""Create-only native Scope PAPER replay through the shared execution/loss owner."""

import argparse
import asyncio
import json
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.options.engine import OptionExecution, fingerprint
from app.options.lifecycle import OptionExecutionPolicy, OptionIntent, OptionReceipt
from app.options.market_tape import RecordedTape
from app.options.models import (
    Money,
    Name,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    OptionRecord,
    UnderlyingQuote,
)
from app.options.operator import OptionsControl, sign
from app.options.operator_models import OptionsCommand
from app.options.replay import _save
from app.options.scope import ScopePreflightInput
from app.options.scope_context import ScopeContextInput
from app.options.scope_execution_export import export_scope_execution
from app.options.scope_replay import MAX_REQUEST_BYTES, ScopeReplayStep, _perform, _revision
from app.options.scope_tape_watch import ScopeTapeWatchAction, resolve_scope_watch_actions
from app.options.scope_watch import ScopeWatchBook, ScopeWatchPolicy
from app.options.venue import DurableOptionVenue


class ScopeNativeStep(OptionRecord):
    kind: Literal["ENTER", "FILL", "CLOSE", "PROTECT", "TERMINAL", "SETTLEMENT", "RESET_LOSS"]
    key: Name
    at: datetime
    play_key: Name | None = None
    order_key: Name | None = None
    frame: ScopePreflightInput | None = None
    context: ScopeContextInput | None = None
    quote: OptionQuote | None = None
    underlying: UnderlyingQuote | None = None
    quantity: int | None = Field(default=None, strict=True, ge=1, le=4)
    terminal: Literal["CANCELED", "EXPIRED", "REJECTED"] | None = None
    receipt: OptionReceipt | None = None
    actor: Name | None = None
    reason: Name | None = None

    @model_validator(mode="after")
    def exact_action(self):
        required, allowed = {
            "ENTER": ({"play_key", "frame", "context", "underlying"}, set()),
            "FILL": ({"order_key", "quote", "quantity"}, {"underlying"}),
            "CLOSE": ({"play_key", "quote"}, {"underlying", "quantity"}),
            "PROTECT": (set(), {"quote", "underlying"}),
            "TERMINAL": ({"order_key", "terminal"}, set()),
            "SETTLEMENT": ({"receipt"}, set()),
            "RESET_LOSS": ({"actor", "reason"}, set()),
        }[self.kind]
        present = {k for k, v in self.model_dump().items() if v is not None} - {"kind", "key", "at"}
        if not required <= present or present - required - allowed:
            raise ValueError("Exact Scope native replay action fields required")
        if self.receipt is not None and self.receipt.occurred_at != self.at:
            raise ValueError("Settlement must be observed at its step")

        def observed(value):
            if isinstance(value, dict):
                if "received_at" in value and value["received_at"] > self.at:
                    raise ValueError("Scope native replay cannot use future received evidence")
                for v in value.values():
                    observed(v)
            elif isinstance(value, (tuple, list)):
                for v in value:
                    observed(v)

        observed(self.model_dump())
        return self


class ScopeExecutionReplay(OptionRecord):
    version: Literal["scope-native-replay-v1"] = "scope-native-replay-v1"
    limits: OptionLimits
    execution: OptionExecutionPolicy
    watch: ScopeWatchPolicy
    started_at: datetime
    steps: tuple[ScopeReplayStep | ScopeNativeStep | ScopeTapeWatchAction, ...] = Field(
        min_length=1, max_length=200
    )
    scope_tape: RecordedTape | None = Field(default=None, exclude_if=lambda v: v is None)
    data_cost: Money | None = Field(default=None, ge=0)
    host_cost: Money | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def enrolled_sequence(self):
        if (
            self.execution.scope_execution != "scope-native-v1"
            or self.watch.native_execution != "scope-native-v1"
        ):
            raise ValueError("Scope native replay requires both frozen enrollments")
        if any(a > b for a, b in pairwise([self.started_at, *(s.at for s in self.steps)])) or len(
            {s.key for s in self.steps}
        ) != len(self.steps):
            raise ValueError("Ordered unique Scope replay steps required")
        if self.scope_tape is None:
            if any(isinstance(s, ScopeTapeWatchAction) for s in self.steps):
                raise ValueError("Tape watch actions require a sealed common Scope tape")
        else:
            header = self.scope_tape.header
            identities = {"population_id", "account_id"}
            if (
                header.scope is None
                or self.watch != header.scope.watch
                or self.limits.model_dump(exclude=identities)
                != header.limits.model_dump(exclude=identities)
                or self.started_at != header.opens_at
                or self.execution.scope_arbitration is not None
                or not all(isinstance(s, ScopeTapeWatchAction) for s in self.steps)
            ):
                raise ValueError("Exact common-tape watch-only owner configuration required")
            resolve_scope_watch_actions(self.scope_tape, self.steps)
        return self


def _intent(engine, source_key, order_links=None):
    with engine.journal.read() as db:
        linked = (order_links or {}).get(source_key)
        row = (
            db.execute(
                "SELECT intent_json FROM execution_orders WHERE client_id=?", (linked,)
            ).fetchone()
            if linked
            else db.execute(
                "SELECT intent_json FROM execution_orders WHERE source_key=?", (source_key,)
            ).fetchone()
        )
        if row is None:
            row = db.execute(
                "SELECT o.intent_json FROM execution_orders o JOIN execution_option_scope_entries e ON e.client_id=o.client_id WHERE e.play_key=?",
                (source_key,),
            ).fetchone()
        if row is None:
            raise ExecutionBlocked("SCOPE_REPLAY_ORDER_REQUIRED")
        return OptionIntent.model_validate_json(row[0])


def _native(engine, venue, book, step, operator_key, order_links):
    if step.kind == "ENTER":
        receipt = book.review_admission(
            "admit-" + fingerprint(step)[:32],
            step.play_key,
            frame=step.frame,
            context=step.context,
            underlying=step.underlying,
            expected_revision=_revision(engine),
            now=step.at,
        )
        if not receipt["record"]["admission_review"]["eligible"]:
            return {"status": "REJECTED", "review": receipt}
        result = book.prepare_entry(step.play_key, expected_revision=_revision(engine), now=step.at)
        if result["status"] == "PREPARED":
            result = result | {
                "dispatch": asyncio.run(
                    engine.dispatch(
                        result["client_id"], step.frame.quote, step.underlying, now=step.at
                    )
                )
            }
        return result
    if step.kind == "CLOSE":
        buy = _intent(engine, step.play_key)
        if buy.side != "BUY":
            raise ExecutionBlocked("SCOPE_REPLAY_BUY_REQUIRED")
        result = engine.prepare(
            step.key,
            OptionProposal(
                action="CLOSE",
                contract=buy.instrument.contract,
                close_quantity=step.quantity,
                thesis="Frozen Scope replay owned close",
            ),
            step.quote,
            step.underlying,
            now=step.at,
        )
        if result["status"] == "PREPARED":
            result = result | {
                "dispatch": asyncio.run(
                    engine.dispatch(result["client_id"], step.quote, step.underlying, now=step.at)
                )
            }
        return result
    if step.kind == "FILL":
        intent = _intent(engine, step.order_key, order_links)
        venue.fill(
            intent, step.quantity, step.quote, step.at, fill_id=step.key, underlying=step.underlying
        )
    elif step.kind == "TERMINAL":
        venue.record_terminal(
            _intent(engine, step.order_key, order_links).client_id, step.terminal, step.at
        )
    elif step.kind == "SETTLEMENT":
        venue.record_receipt(step.receipt)
    elif step.kind == "PROTECT":
        return asyncio.run(engine.protective_tick(step.quote, step.underlying, now=step.at))
    elif step.kind == "RESET_LOSS":
        with engine.journal.read() as db:
            binding = db.execute("SELECT * FROM execution_operator").fetchone()
        from datetime import timedelta

        command = OptionsCommand(
            journal_id=binding["journal_id"],
            population_id=engine.limits.population_id,
            command_id=uuid4().hex,
            credential_generation=binding["generation"],
            actor=step.actor,
            action="RESET_LOSS_LOCK",
            loss_family="SCOPE",
            reason=step.reason,
            expected_revision=_revision(engine),
            issued_at=step.at,
            expires_at=step.at + timedelta(seconds=60),
        )
        return OptionsControl(engine, operator_key).apply(
            command, sign(command, operator_key), now=step.at
        )
    result = engine.reconcile(venue.snapshot(step.at), now=step.at)
    if not result["reconciled"]:
        raise ValueError("Scope replay native reconciliation failed")
    return result


def run_scope_execution_replay(request, directory):
    request = ScopeExecutionReplay.model_validate(request.model_dump(warnings=False))
    if len(request.model_dump_json().encode()) > MAX_REQUEST_BYTES:
        raise ValueError("Bounded Scope replay request required")
    resolved = (
        resolve_scope_watch_actions(request.scope_tape, request.steps)
        if request.scope_tape is not None
        else tuple((s, None) for s in request.steps)
    )
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute new Scope execution replay directory required")
    directory.mkdir(mode=0o700)
    digest = fingerprint(request)
    _save(
        directory / "inputs.json",
        {"request_hash": digest, "request": request.model_dump(mode="json")},
    )
    # A local fixture credential, generated for this isolated owner and never exported.
    import secrets

    key = secrets.token_bytes(32)
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
            engine.reconcile(venue.snapshot(request.started_at), now=request.started_at)
            engine.assess(None, None, now=request.started_at)
            book = ScopeWatchBook(engine, request.watch, now=request.started_at, create=True)
            if any(s.kind == "RESET_LOSS" for s in request.steps):
                OptionsControl.enroll(engine, key, now=request.started_at)
            actions = []
            order_links = {}
            for original, (step, binding) in zip(request.steps, resolved, strict=True):
                if not engine.reconcile(venue.snapshot(step.at), now=step.at)["reconciled"]:
                    raise ValueError("Scope replay reconciliation failed")
                engine.assess(getattr(step, "quote", None), step.underlying, now=step.at)
                before = _revision(engine)
                try:
                    result = (
                        _perform(book, step, before)
                        if isinstance(step, ScopeReplayStep)
                        else _native(engine, venue, book, step, key, order_links)
                    )
                except ExecutionBlocked as exc:
                    if binding is not None and _revision(engine) != before:
                        raise ValueError("Rejected tape watch action changed its journal") from exc
                    result = {"status": "REJECTED", "reason": str(exc)}
                if result.get("client_id") is not None:
                    order_links[step.key] = result["client_id"]
                actions.append(
                    {
                        "key": step.key,
                        "kind": step.kind,
                        "at": step.at.isoformat(),
                        "step_hash": fingerprint(original),
                        **(
                            {"tape_binding": binding, "expected_revision": before}
                            if binding is not None
                            else {}
                        ),
                        "result": result,
                    }
                )
            now = request.steps[-1].at
            if request.scope_tape is not None:
                with engine.journal.read() as db:
                    for table in (
                        "execution_orders",
                        "execution_fills",
                        "execution_model_calls",
                        "execution_option_decisions",
                    ):
                        if db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                            raise ValueError("Tape watch replay produced native trading activity")
            export = export_scope_execution(
                engine.journal, now=now, data_cost=request.data_cost, host_cost=request.host_cost
            )
            _save(directory / "native.json", export)
            report = {
                "version": request.version,
                "status": (
                    "COMPLETE_TAPE_WATCH_REPLAY"
                    if request.scope_tape is not None
                    else "COMPLETE_FIXTURE_REPLAY"
                ),
                **(
                    {
                        "tape_hash": request.scope_tape.digest,
                        "comparison_complete": False,
                        "economic_conclusion": "NOT_EVALUATED",
                    }
                    if request.scope_tape is not None
                    else {}
                ),
                "request_hash": digest,
                "export_hash": export["export_hash"],
                "actions": actions,
                "accounting": export["report"],
                "execution_authority": False,
                "live_enabled": False,
            }
            _save(directory / "report.json", report)
            return report
    except BaseException:
        _save(
            directory / "interrupted.json",
            {"status": "INCOMPLETE_FIXTURE_REPLAY", "request_hash": digest},
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.request.stat().st_size > MAX_REQUEST_BYTES:
        parser.error("Scope request is too large")
    report = run_scope_execution_replay(
        ScopeExecutionReplay.model_validate_json(args.request.read_bytes()), args.directory
    )
    print(
        json.dumps(
            {k: report[k] for k in ("status", "request_hash", "export_hash")}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
