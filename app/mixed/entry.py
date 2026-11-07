"""Full original share evidence and paid entry binding on the native mixed owner."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.mixed.governor import admit_stock
from app.mixed.models import CashHistory, StockAdmission
from app.mixed.portfolio_accounting import PortfolioHistory, PortfolioStockAdmission
from app.mixed.sources import (
    StockCycleInput,
    StockSelectionPolicy,
    StockSourceCandidate,
    candidates,
)
from app.options.degen import DegenHistory, DegenPolicy
from app.options.engine import fingerprint
from app.options.lifecycle import OptionExecutionPolicy
from app.options.models import OptionAccount, OptionRecord, SessionWindow
from app.robinhood.schedule import XNYSCalendar


class StockEntryEvidence(OptionRecord):
    swing_unavailable: bool = Field(default=False, strict=True, exclude_if=lambda v: not v)
    candidate: StockSourceCandidate
    admission: PortfolioStockAdmission | StockAdmission
    account_revision: int = Field(ge=0, strict=True)
    snapshot_id: str
    history: PortfolioHistory | CashHistory
    account: OptionAccount
    session: SessionWindow
    source: StockCycleInput
    intraday: DegenHistory
    structure: DegenPolicy
    selection: StockSelectionPolicy
    execution: OptionExecutionPolicy
    as_of: datetime

    @model_validator(mode="after")
    def bound(self):
        if self.swing_unavailable and not isinstance(self.history, PortfolioHistory):
            raise ValueError("Unavailable Swing requires portfolio evidence")
        rebuilt, _, _ = candidates(
            self.source,
            self.intraday,
            self.structure,
            self.selection,
            self.execution,
            XNYSCalendar(),
            now=self.as_of,
            swing_unavailable=self.swing_unavailable,
        )
        actual = admit_stock(
            self.candidate.proposal,
            self.source.quote,
            self.history,
            self.session,
            now=self.history.captured_at,
            reconciled=self.account.reconciled,
            entry_halted=self.account.entry_halted,
        )
        if actual.outcome == "APPROVED":
            actual = actual.model_copy(
                update={
                    "approval_expires_at": min(
                        actual.approval_expires_at,
                        self.account.captured_at
                        + timedelta(seconds=self.history.policy.options.account_max_age_seconds),
                    )
                }
            )
        if (
            self.candidate not in rebuilt
            or actual != self.admission
            or actual.outcome != "APPROVED"
            or self.account.snapshot_id != self.snapshot_id
            or self.history.account_id != self.account.account_id
            or self.execution.mixed_owner is None
            or self.execution.mixed_owner.reasoning != "mixed-paid-entry-v1"
            or not self.as_of <= self.history.captured_at < actual.approval_expires_at
        ):
            raise ValueError("Original stock source, owner and complete admission required")
        return self


def evidence_for(c, key, evidence):
    from app.options.coordinator import DegenFrame

    with c.engine.journal.read() as db:
        row = db.execute(
            "SELECT inputs_json,started_at FROM execution_option_opportunities WHERE cycle_key=?",
            (key,),
        ).fetchone()
    frame = DegenFrame.model_validate_json(row[0])
    return tuple(
        StockEntryEvidence(
            **raw,
            swing_unavailable=frame.swing_unavailable,
            source=next(
                x
                for x in frame.stocks
                if x.quote.instrument.instrument_id
                == raw["candidate"]["proposal"]["instrument"]["instrument_id"]
            ),
            intraday=next(
                x
                for x in frame.histories
                if x.symbol == raw["candidate"]["proposal"]["instrument"]["symbol"]
            ),
            structure=c.policy,
            selection=c.stock_policy,
            execution=c.engine.policy,
            as_of=datetime.fromisoformat(row[1]),
        )
        for raw in evidence.get("stock_candidates", [])
    )


def review_original(packet, plan):
    matches = [o for o in packet.stocks if o.candidate.candidate_id == plan.candidate_id]
    if (
        not getattr(plan, "stock", False)
        or getattr(plan, "scope", False)
        or len(matches) != 1
        or fingerprint(matches[0]) not in plan.evidence_ids
    ):
        raise ValueError("Exact original admitted stock evidence required")
    return matches[0]


def validate_stored(db, key, evidence, *, usable=True):
    from app.options import entry_judgment as j

    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    owner = OptionExecutionPolicy.model_validate(
        json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )["policy"]
    )
    request = j.EntryRequest.model_validate(evidence["entry_request"])
    call = db.execute("SELECT * FROM execution_model_calls WHERE source_key=?", (key,)).fetchone()
    if (
        owner.mixed_owner is None
        or owner.mixed_owner.reasoning != "mixed-paid-entry-v1"
        or request.packet.policy.mixed_selection is None
        or config.get("entry_model") != request.configuration.model_dump(mode="json")
        or request.configuration.costs != owner.cost_policy
        or request.packet.cycle_key != key
        or call is None
        or call["packet_hash"] != fingerprint(j.request_content(request))
    ):
        raise ExecutionBlocked("MIXED_FULL_ENTRY_REQUEST_REQUIRED")
    from app.options.coordinator import DegenFrame

    row = db.execute(
        "SELECT inputs_json,started_at,fingerprint FROM execution_option_opportunities WHERE cycle_key=?",
        (key,),
    ).fetchone()
    frame = DegenFrame.model_validate_json(row["inputs_json"])
    if (
        fingerprint(frame) != row["fingerprint"]
        or [o.candidate.model_dump(mode="json") for o in request.packet.opportunities]
        != evidence.get("candidates", [])
        or (request.packet.scope.model_dump(mode="json") if request.packet.scope else None)
        != evidence.get("scope_candidate")
        or [
            o.model_dump(
                mode="json",
                exclude={"source", "intraday", "structure", "selection", "execution", "as_of"},
            )
            for o in request.packet.stocks
        ]
        != evidence.get("stock_candidates", [])
    ):
        raise ExecutionBlocked("MIXED_ORIGINAL_ALTERNATIVES_CHANGED")
    for o in request.packet.stocks:
        if (
            o.execution != owner
            or o.selection.model_dump(mode="json") != config.get("stocks")
            or o.structure.model_dump(mode="json") != config.get("setup")
            or o.source not in frame.stocks
            or o.intraday not in frame.histories
            or o.as_of != datetime.fromisoformat(row["started_at"])
        ):
            raise ExecutionBlocked("MIXED_ORIGINAL_SOURCE_PACKET_CHANGED")
    result = (
        j.EntryResult.model_validate(evidence["entry_result"])
        if "entry_result" in evidence
        else None
    )
    if call["cost"] is not None:
        if (
            result is None
            or result.usage is None
            or result.request_id != request.request_id
            or result.packet_hash != fingerprint(request.packet)
            or result.configuration_hash != fingerprint(request.configuration)
            or result.plan.packet_hash != fingerprint(request.packet)
            or result.plan.decision_id != request.packet.decision_id
            or call["decision_hash"] != fingerprint(result.plan)
            or call["usage_json"] != result.usage.model_dump_json()
            or call["request_id"] != result.usage.request_id
            or result.usage.model != owner.cost_policy.model
        ):
            raise ExecutionBlocked("MIXED_FULL_ENTRY_RECEIPT_REQUIRED")
        from app.options.engine import exact

        @exact
        def amount():
            return (
                result.usage.input_tokens * owner.cost_policy.input_per_million
                + result.usage.output_tokens * owner.cost_policy.output_per_million
            ) / Decimal(1000000)

        if Decimal(call["cost"]) != amount():
            raise ExecutionBlocked("MIXED_ENTRY_CHARGE_CHANGED")
    if usable:
        if (
            result is None
            or call["cost"] is None
            or result.error is not None
            or result.plan.action != "ENTER"
            or evidence.get("entry_timely") is not True
            or not request.packet.as_of
            <= datetime.fromisoformat(evidence["entry_completed_at"])
            < request.packet.valid_until
            or Decimal(call["cost"]) > owner.cost_policy.max_call_cost
        ):
            raise ExecutionBlocked("MIXED_USABLE_PAID_ENTRY_REQUIRED")
        j.validate_result(request, result)
    return request, result, call


def validate_admission(engine, db, key, input_hash, now):
    from app.mixed.selection import configuration, receipt
    from app.options import entry_judgment as j

    row = db.execute(
        "SELECT status,result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    if row is None or row["status"] != "STARTED":
        raise ExecutionBlocked("MIXED_ORIGINAL_ENTRY_SLOT_REQUIRED")
    evidence = json.loads(row["result_json"])
    request = j.EntryRequest.model_validate(evidence["entry_request"])
    frozen = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    if engine.portfolio_policy is not None:
        from app.mixed.portfolio_execution import selection_account
        from app.mixed.portfolio_store import history

        account = selection_account(engine, db, now)
        h = history(engine, db, engine.portfolio_policy, now)
        if request.packet.portfolio_history is None or request.packet.portfolio_history.model_dump(
            exclude={"captured_at"}
        ) != h.model_dump(exclude={"captured_at"}):
            raise ExecutionBlocked("PORTFOLIO_MODEL_ACCOUNT_CHANGED")
    else:
        account = engine._account(db, now)
    if (
        request.packet.cycle_key != key
        or request.packet.policy.mixed_selection is None
        or request.configuration.costs != engine.policy.cost_policy
        or request.configuration.model_dump(mode="json") != frozen.get("entry_model")
        or input_hash != fingerprint(j.request_content(request))
        or request.packet.limits != engine._effective_limits()
        or request.packet.account != account
        or not request.packet.as_of <= now < request.packet.valid_until
        or evidence.get("mixed_selection") != receipt(configuration(db), key, evidence)
    ):
        raise ExecutionBlocked("MIXED_ORIGINAL_ENTRY_ADMISSION_CHANGED")
    for item in request.packet.stocks:
        raw = item.model_dump(
            mode="json",
            exclude={"source", "intraday", "structure", "selection", "execution", "as_of"},
        )
        if raw not in evidence.get("stock_candidates", []) or item.execution != engine.policy:
            raise ExecutionBlocked("MIXED_STOCK_ALTERNATIVES_CHANGED")


def stock_ceiling(db, key, data, candidate, *, now, original):
    request, result, _ = validate_stored(db, key, data)
    selected = review_original(request.packet, result.plan)
    if selected.candidate != candidate or (
        not original and not request.packet.as_of <= now < request.packet.valid_until
    ):
        raise ExecutionBlocked("MIXED_ORIGINAL_PAID_STOCK_CHANGED")
    return min(selected.admission.approval_expires_at, request.packet.valid_until)


async def execute(c, key, evidence, request, result):
    import asyncio

    from app.mixed.selection import select
    from app.mixed.stock_models import StockQuote

    with c.engine.journal.read() as db:
        validate_stored(db, key, evidence)
    original = review_original(request.packet, result.plan)
    select(c, key, evidence)
    try:
        async with asyncio.timeout(max(0, (request.packet.valid_until - c.now()).total_seconds())):
            quote = await c.stock_refresh(original.candidate.proposal.instrument)
        quote = StockQuote.model_validate(quote.model_dump(warnings=False))
        if (
            quote.instrument != original.source.quote.instrument
            or quote.source_at < original.source.quote.source_at
        ):
            raise ValueError("Fresh stock identity or clock regressed")
    except (TimeoutError, ValueError):
        return c._finish(
            key, {**evidence, "status": "HOLD", "reason": "STOCK_FRESH_PAID_EVIDENCE_REQUIRED"}
        )
    evidence["stock_fresh_quote"] = quote.model_dump(mode="json")
    c._pending_evidence(key, evidence)
    prepared = c.engine.prepare_stock(
        key, original.candidate.proposal, quote, now=c.now(), origin="MODEL"
    )
    if prepared["status"] != "PREPARED":
        return c._finish(
            key,
            {
                **evidence,
                "status": "HOLD",
                "prepared": prepared,
                "reason": "STOCK_POST_COST_ADMISSION_REJECTED",
            },
        )
    status = await c.engine.dispatch_stock(prepared["client_id"], quote, now=c.now())
    return c._finish(
        key,
        {
            **evidence,
            "status": status,
            "prepared": prepared,
            "client_id": prepared["client_id"],
            "candidate_id": original.candidate.candidate_id,
            "selected_family": original.candidate.proposal.family,
            "selected_asset": "STOCK",
        },
    )
