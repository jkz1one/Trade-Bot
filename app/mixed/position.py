"""Paid share management retains original entry terms and independent native exits."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from app.execution.engine import ExecutionBlocked
from app.mixed.entry import StockEntryEvidence
from app.mixed.governor import admit_stock
from app.mixed.models import CashHistory, StockProposal
from app.mixed.native_models import StockProtection
from app.mixed.stock_models import StockIntent, StockPosition, StockQuote
from app.options.degen import DegenScan
from app.options.engine import fingerprint
from app.options.entry_reasoning import Digest, MixedEntryPlan
from app.options.lifecycle import OptionExecutionPolicy
from app.options.models import Name, OptionAccount, OptionLimits, OptionRecord, SessionWindow
from app.options.position_reasoning import PositionPlan, PositionReasoningPolicy, PositionReview


class StockPositionPacket(OptionRecord):
    version: Literal["mixed-stock-position-packet-v1"] = "mixed-stock-position-packet-v1"
    mode: Literal["PAPER"] = "PAPER"
    decision_id: Digest
    cycle_key: Name
    model_configuration_hash: Digest
    as_of: datetime
    valid_until: datetime
    position_revision: int = Field(gt=0, strict=True)
    position: StockPosition
    entry: StockIntent
    original_source: StockEntryEvidence
    entry_thesis: MixedEntryPlan
    protection: StockProtection
    history: CashHistory
    account: OptionAccount
    quote: StockQuote
    scan: DegenScan
    session: SessionWindow
    limits: OptionLimits
    execution_policy: OptionExecutionPolicy
    policy: PositionReasoningPolicy
    evidence_ids: tuple[Digest, Digest, Digest, Digest, Digest, Digest]

    @property
    def underlying(self):
        return None

    @model_validator(mode="after")
    def bound(self):
        e, p = self.entry, self.position
        if (
            self.policy.mixed_management != "mixed-stock-position-v1"
            or self.execution_policy.mixed_owner is None
            or self.execution_policy.mixed_owner.reasoning is None
            or self.original_source.execution != self.execution_policy
            or self.cycle_key != "position:" + str(int(self.as_of.timestamp()) // 300)
            or not self.as_of
            < self.valid_until
            <= min(e.exit_at, self.as_of + timedelta(seconds=self.policy.max_lease_seconds))
            or self.valid_until.timestamp() > (int(self.as_of.timestamp()) // 300 + 1) * 300
            or p.entry != e
            or e.instrument != self.quote.instrument
            or self.original_source.candidate.proposal.source_hash != e.source_hash
            or self.entry_thesis.candidate_id != self.original_source.candidate.candidate_id
            or not self.entry_thesis.stock
            or self.entry_thesis.action != "ENTER"
            or self.protection.entry_client_id != e.client_id
            or self.protection.exit_reason
            or self.protection.issue
            or self.scan.symbol != e.instrument.symbol
            or self.scan.issues
            or self.scan.evaluated_at != self.as_of
            or self.evidence_ids
            != tuple(
                fingerprint(x) for x in (p, e, self.account, self.quote, self.protection, self.scan)
            )
        ):
            raise ValueError(
                "Complete original healthy stock position and current context required"
            )
        close = admit_stock(
            StockProposal(
                action="CLOSE", instrument=e.instrument, thesis="Owned management preflight"
            ),
            self.quote,
            self.history,
            self.session,
            now=self.as_of,
            reconciled=self.account.reconciled,
            entry_halted=self.account.entry_halted,
        )
        if (
            close.outcome != "APPROVED"
            or close.quantity != p.quantity
            or not self.account.budgets_known
            or self.account.entry_halted
            or self.account.entry_blockers
            or self.account.working_orders
            or self.account.position is None
            or self.account.position.quantity != p.quantity
            or not self.protection.invalidation < self.quote.bid < e.original_target
        ):
            raise ValueError("Original stock management admission required")
        return self


def review(packet, plan, *, position, account, quote, now, protection=None):
    packet = StockPositionPacket.model_validate(packet.model_dump(warnings=False))
    plan = PositionPlan.model_validate(plan.model_dump(warnings=False))
    guard = protection or packet.protection

    def out(status, reason, **kw):
        return PositionReview(
            outcome=status, reasons=(reason,), packet_hash=fingerprint(packet), plan=plan, **kw
        )

    if (
        plan.packet_hash != fingerprint(packet)
        or plan.decision_id != packet.decision_id
        or plan.entry_client_id != packet.entry.client_id
        or plan.position_revision != packet.position_revision
        or not {packet.evidence_ids[0], packet.evidence_ids[5]}
        <= set(plan.evidence_ids)
        <= set(packet.evidence_ids)
    ):
        return out("REJECTED", "STOCK_POSITION_PLAN_BINDING")
    if (
        guard.exit_reason
        or now >= packet.entry.exit_at
        or (
            quote is not None
            and (quote.bid <= guard.invalidation or quote.bid >= packet.entry.original_target)
        )
    ):
        return out("MANDATORY_EXIT", "STOCK_MANDATORY_EXIT_PRECEDES_MODEL")
    if (
        position != packet.position
        or guard != packet.protection
        or quote is None
        or quote.instrument != packet.quote.instrument
        or quote.source_at < packet.quote.source_at
        or not packet.as_of <= now < packet.valid_until
        or account.entry_halted
        or account.entry_blockers
        or not account.budgets_known
        or account.working_orders
        or not timedelta(0)
        <= now - account.captured_at
        < timedelta(seconds=packet.limits.account_max_age_seconds)
    ):
        return out("REJECTED", "STOCK_CURRENT_POSITION_OR_DEADLINE_CHANGED")
    from app.options.governor import _fresh

    limits = packet.execution_policy.mixed_owner.stocks
    if (
        quote.source != limits.quote_source
        or not quote.complete
        or quote.entitlement != "REALTIME"
        or not _fresh(
            quote.source_at,
            quote.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        return out("REJECTED", "STOCK_FRESH_MANAGEMENT_QUOTE_REQUIRED")
    if plan.action == "MAINTAIN":
        return out("MAINTAIN", "MODEL_MAINTAIN")
    if plan.action == "TIGHTEN":
        if not guard.invalidation < plan.underlying_invalidation < quote.bid:
            return out("REJECTED", "STOCK_INVALIDATION_CANNOT_WIDEN_OR_CROSS")
        return out(
            "ELIGIBLE",
            "STOCK_TIGHTEN_REQUESTED",
            tightened_invalidation=plan.underlying_invalidation,
        )
    return out("ELIGIBLE", "STOCK_OWNED_FULL_CLOSE_REQUESTED")


def stored(db, key, *, usable=False):
    from app.options import position_judgment as j

    row = db.execute(
        "SELECT * FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    data = json.loads(row["result_json"] or "{}") if row else {}
    request = j.PositionRequest.model_validate(data["position_request"])
    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    call = db.execute("SELECT * FROM execution_model_calls WHERE source_key=?", (key,)).fetchone()
    packet = request.packet
    if (
        not isinstance(packet, StockPositionPacket)
        or packet.cycle_key != "position:" + key.split(":")[1]
        or config.get("position_model") != request.configuration.model_dump(mode="json")
        or call is None
        or call["packet_hash"] != fingerprint(j.request_content(request))
    ):
        raise ExecutionBlocked("STOCK_FULL_MANAGEMENT_REQUEST_REQUIRED")
    verify_context(db, row, packet, config)
    from app.mixed.entry import review_original, validate_stored
    from app.mixed.native_store import verify_order

    entryrow = db.execute(
        "SELECT * FROM execution_stock_orders WHERE client_id=?", (packet.entry.client_id,)
    ).fetchone()
    if entryrow is None or verify_order(db, entryrow) != packet.entry:
        raise ExecutionBlocked("STOCK_ORIGINAL_MANAGEMENT_ENTRY_CHANGED")
    evidence = json.loads(
        db.execute(
            "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
            (packet.entry.source_key,),
        ).fetchone()[0]
    )
    original, plan, _ = validate_stored(db, packet.entry.source_key, evidence)
    if (
        packet.original_source != review_original(original.packet, plan.plan)
        or packet.entry_thesis != plan.plan
    ):
        raise ExecutionBlocked("STOCK_ORIGINAL_MANAGEMENT_THESIS_CHANGED")
    result = (
        j.PositionResult.model_validate(data["position_result"])
        if "position_result" in data
        else None
    )
    if call["cost"] is not None:
        from decimal import Decimal

        from app.options.engine import exact

        @exact
        def charge():
            return (
                result.usage.input_tokens * request.configuration.costs.input_per_million
                + result.usage.output_tokens * request.configuration.costs.output_per_million
            ) / Decimal(1000000)

        if (
            result is None
            or result.usage is None
            or result.request_id != request.request_id
            or result.packet_hash != fingerprint(packet)
            or result.configuration_hash != fingerprint(request.configuration)
            or result.plan.packet_hash != fingerprint(packet)
            or result.plan.decision_id != packet.decision_id
            or result.plan.entry_client_id != packet.entry.client_id
            or result.plan.position_revision != packet.position_revision
            or result.usage.model != request.configuration.costs.model
            or call["usage_json"] != result.usage.model_dump_json()
            or call["decision_hash"] != fingerprint(result.plan)
            or call["request_id"] != result.usage.request_id
            or Decimal(call["cost"]) != charge()
        ):
            raise ExecutionBlocked("STOCK_FULL_MANAGEMENT_RECEIPT_REQUIRED")
    decision = db.execute(
        "SELECT inputs_json,result_json FROM execution_stock_decisions WHERE source_key=?", (key,)
    ).fetchone()
    if decision:
        inputs, applied = json.loads(decision[0]), json.loads(decision[1])
        if (
            inputs.get("position_request") != request.model_dump(mode="json")
            or result is None
            or inputs.get("position_result") != result.model_dump(mode="json")
        ):
            raise ExecutionBlocked("STOCK_MANAGEMENT_APPLICATION_CHANGED")
        if applied.get("status") == "TIGHTENED":
            events = db.execute(
                "SELECT payload FROM execution_events WHERE kind='STOCK_INVALIDATION_TIGHTENED' AND json_extract(payload,'$.source_key')=?",
                (key,),
            ).fetchall()
            if (
                result.plan.action != "TIGHTEN"
                or len(events) != 1
                or json.loads(events[0][0])
                != {"source_key": key, "price": str(result.plan.underlying_invalidation)}
            ):
                raise ExecutionBlocked("STOCK_MANAGEMENT_STOP_EVENT_CHANGED")
        if applied.get("client_id"):
            order = db.execute(
                "SELECT intent_json,approval_json FROM execution_stock_orders WHERE client_id=?",
                (applied["client_id"],),
            ).fetchone()
            if (
                result.plan.action != "EXIT_ALL"
                or order is None
                or json.loads(order[0]).get("closing_entry_client_id") != packet.entry.client_id
                or json.loads(order[1])["inputs"] != inputs
            ):
                raise ExecutionBlocked("STOCK_MANAGEMENT_CLOSE_APPLICATION_CHANGED")
    if usable:
        if (
            result is None
            or call["cost"] is None
            or result.error is not None
            or data.get("position_timely") is not True
            or not packet.as_of
            <= datetime.fromisoformat(data["position_completed_at"])
            < packet.valid_until
        ):
            raise ExecutionBlocked("STOCK_USABLE_PAID_MANAGEMENT_REQUIRED")
        j.validate_result(request, result)
    return request, result, call, data


def verify_context(db, row, packet, config):
    from app.options.coordinator import DegenFrame
    from app.options.degen import DegenPolicy, scan_degen
    from app.robinhood.schedule import XNYSCalendar

    frame = DegenFrame.model_validate_json(row["inputs_json"])
    histories = [h for h in frame.histories if h.symbol == packet.entry.instrument.symbol]
    quotes = [x.quote for x in frame.stocks if x.quote.instrument == packet.entry.instrument]
    owner = json.loads(
        db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
    )
    if (
        fingerprint(frame) != row["fingerprint"]
        or len(histories) != 1
        or quotes != [packet.quote]
        or packet.execution_policy.model_dump(mode="json") != owner["policy"]
        or packet.as_of < datetime.fromisoformat(row["started_at"])
        or packet.scan
        != scan_degen(
            histories[0],
            DegenPolicy.model_validate(config["setup"]),
            XNYSCalendar().current_window(packet.as_of),
            now=packet.as_of,
        )
    ):
        raise ExecutionBlocked("STOCK_CURRENT_MANAGEMENT_CONTEXT_CHANGED")


def validate_admission(engine, db, key, request, input_hash, now):
    from app.mixed.native_store import position, protection
    from app.options import position_judgment as j

    row = db.execute(
        "SELECT * FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    data = json.loads(row["result_json"] or "{}") if row else {}
    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    p = request.packet
    if (
        row is None
        or row["status"] != "STARTED"
        or p.execution_policy != engine.policy
        or config.get("position_model") != request.configuration.model_dump(mode="json")
        or data.get("position_request") != request.model_dump(mode="json")
        or p.position_revision != engine.journal.revision(db)
        or p.position != position(engine, db)
        or p.protection != protection(engine, db)
        or p.account != engine._account(db, now)
        or input_hash != fingerprint(j.request_content(request))
        or not p.as_of <= now < p.valid_until
    ):
        raise ExecutionBlocked("STOCK_MANAGEMENT_ADMISSION_CHANGED")
    verify_context(db, row, p, config)


def close_guard(engine, db, key, proposal, quote, now, *, original=False, exclude=None):
    request, result, _, _ = stored(db, key, usable=True)
    p = request.packet
    if (
        result.plan.action != "EXIT_ALL"
        or proposal.action != "CLOSE"
        or proposal.instrument != p.entry.instrument
    ):
        raise ExecutionBlocked("STOCK_EXACT_MANAGEMENT_CLOSE_REQUIRED")
    if not original:
        from app.mixed.native_store import position, protection

        checked = review(
            p,
            result.plan,
            position=position(engine, db),
            protection=protection(engine, db),
            account=engine._account(db, now, exclude=exclude, closing=True),
            quote=quote,
            now=now,
        )
        if checked.outcome != "ELIGIBLE":
            raise ExecutionBlocked(";".join(checked.reasons))
    return p.valid_until


def apply(c, key, request, result, quote, now):
    from app.mixed.native_execution import prepare
    from app.mixed.native_store import position, protection

    with c.engine.journal.write() as db:
        c._bound(db)
        verified_request, verified_result, _, _ = stored(db, key, usable=True)
        if request != verified_request or result != verified_result:
            raise ExecutionBlocked("STOCK_MANAGEMENT_APPLICATION_CHANGED")
        prior = db.execute(
            "SELECT inputs_json,result_json FROM execution_stock_decisions WHERE source_key=?",
            (key,),
        ).fetchone()
        if prior:
            inputs = json.loads(prior[0])
            if inputs.get("position_request") != request.model_dump(mode="json") or inputs.get(
                "position_result"
            ) != result.model_dump(mode="json"):
                raise ExecutionBlocked("STOCK_MANAGEMENT_APPLICATION_CHANGED")
            return json.loads(prior[1])
        if db.execute(
            "SELECT 1 FROM execution_stock_decisions WHERE json_extract(inputs_json,'$.position_request.packet.position_revision')=?",
            (request.packet.position_revision,),
        ).fetchone():
            raise ExecutionBlocked("STOCK_POSITION_REVISION_ALREADY_CONSUMED")
        checked = review(
            request.packet,
            result.plan,
            position=position(c.engine, db),
            protection=protection(c.engine, db),
            account=c.engine._account(db, now),
            quote=quote,
            now=now,
        )
        if checked.outcome == "ELIGIBLE" and result.plan.action == "EXIT_ALL":
            return prepare(
                c.engine,
                key,
                StockProposal(
                    action="CLOSE",
                    instrument=request.packet.entry.instrument,
                    thesis=result.plan.thesis,
                ),
                quote,
                now=now,
                origin="POSITION_MODEL",
                close_quantity=None,
                _db=db,
            )
        output = {
            "status": checked.outcome,
            "position_review": checked.model_dump(mode="json"),
            "client_id": None,
        }
        inputs = {
            "position_request": request.model_dump(mode="json"),
            "position_result": result.model_dump(mode="json"),
        }
        if checked.outcome == "ELIGIBLE":
            guard = protection(c.engine, db).model_copy(
                update={"invalidation": checked.tightened_invalidation}
            )
            db.execute(
                "UPDATE execution_mixed_control SET protection_json=? WHERE id=1",
                (guard.model_dump_json(),),
            )
            c.engine.journal.event(
                db,
                now,
                "STOCK_INVALIDATION_TIGHTENED",
                {"source_key": key, "price": str(guard.invalidation)},
                request.packet.entry.client_id,
            )
            output["status"] = "TIGHTENED"
        db.execute(
            "INSERT INTO execution_stock_decisions VALUES(?,?,?,?)",
            (
                key,
                fingerprint(inputs),
                json.dumps(inputs, sort_keys=True),
                json.dumps(output, sort_keys=True),
            ),
        )
        c.engine.journal.event(
            db, now, "STOCK_POSITION_PLAN_APPLIED", {"source_key": key, **output}
        )
        return output


async def run(c, key, frame):
    from app.mixed.entry import review_original, validate_stored
    from app.mixed.native_execution import session
    from app.mixed.native_store import history, position, protection
    from app.options import position_judgment as j
    from app.options.degen import scan_degen

    evidence = {"entry_allowed": False}
    at = c.now()
    try:
        secret = c._model_secret()
        config = j.configuration(c.engine.policy.cost_policy, c.judgment_limits, c.position_policy)
        with c.engine.journal.read() as db:
            p = position(c.engine, db)
            guard = protection(c.engine, db)
            account = c.engine._account(db, at)
            quotes = [x.quote for x in frame.stocks if x.quote.instrument == p.instrument]
            histories = [h for h in frame.histories if h.symbol == p.instrument.symbol]
            if len(quotes) != 1 or len(histories) != 1:
                raise ValueError("Exact held stock context required")
            q = quotes[0]
            scan = scan_degen(histories[0], c.policy, c.engine.calendar.current_window(at), now=at)
            original = json.loads(
                db.execute(
                    "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?",
                    (p.entry.source_key,),
                ).fetchone()[0]
            )
            entry_request, entry_result, _ = validate_stored(db, p.entry.source_key, original)
            packet = StockPositionPacket(
                decision_id=fingerprint(
                    {
                        "population": c.engine.limits.population_id,
                        "cycle": key,
                        "configuration": config,
                    }
                ),
                cycle_key="position:" + key.split(":")[1],
                model_configuration_hash=fingerprint(config),
                as_of=at,
                valid_until=min(
                    p.entry.exit_at,
                    at + timedelta(seconds=c.position_policy.max_lease_seconds),
                    datetime.fromtimestamp((int(at.timestamp()) // 300 + 1) * 300, tz=at.tzinfo),
                ),
                position_revision=c.engine.journal.revision(db),
                position=p,
                entry=p.entry,
                original_source=review_original(entry_request.packet, entry_result.plan),
                entry_thesis=entry_result.plan,
                protection=guard,
                history=history(c.engine, db, as_of=at),
                account=account,
                quote=q,
                scan=scan,
                session=session(c.engine, p.instrument, at),
                limits=c.engine._effective_limits(),
                execution_policy=c.engine.policy,
                policy=c.position_policy,
                evidence_ids=tuple(fingerprint(x) for x in (p, p.entry, account, q, guard, scan)),
            )
        request = j.create_request(packet, config, request_id=uuid4().hex, now=at)
        if len(request.model_dump_json().encode()) > j.MAX_REQUEST_BYTES:
            raise ValueError("Stock management request capacity")
    except (OSError, ValueError, ExecutionBlocked):
        return c._finish(
            key, {**evidence, "status": "HELD", "reason": "STOCK_POSITION_PREFLIGHT_UNAVAILABLE"}
        )
    evidence["position_request"] = request.model_dump(mode="json")
    c._pending_evidence(key, evidence)
    try:
        c.engine.begin_model_attempt(
            key, fingerprint(j.request_content(request)), now=at, position_request=request
        )
    except ExecutionBlocked as exc:
        return c._finish(key, {**evidence, "status": "HELD", "reason": str(exc)})
    try:
        result = await j.run_position_process(request, secret)
        result = j.PositionResult.model_validate(result.model_dump(warnings=False))
        completed = c.now()
        evidence.update(
            position_result=result.model_dump(mode="json"),
            position_completed_at=completed.isoformat(),
            position_timely=c._model_timely(request, at, completed)
            and at <= completed < packet.valid_until,
        )
        c._pending_evidence(key, evidence)
        if (
            result.request_id != request.request_id
            or result.packet_hash != fingerprint(packet)
            or result.configuration_hash != fingerprint(config)
            or result.plan.packet_hash != fingerprint(packet)
            or result.plan.decision_id != packet.decision_id
            or result.plan.entry_client_id != p.entry.client_id
            or result.plan.position_revision != packet.position_revision
            or result.usage is None
            or result.usage.model != config.costs.model
            or completed < at
        ):
            raise ValueError("Unknown management usage")
        c.engine.record_position_usage(key, result.usage, result.plan, now=completed)
    except Exception as exc:  # noqa: BLE001 -- retain unknown charge without private error text
        c._model_halt("OPTION_MODEL_COST_UNKNOWN", c.now())
        evidence["management"] = await c.engine.protective_stock_tick(q, now=c.now())
        return c._finish(
            key,
            {
                **evidence,
                "status": "HELD",
                "reason": "OPTION_MODEL_COST_UNKNOWN",
                "model_error_class": type(exc).__name__,
            },
        )
    try:
        async with asyncio.timeout(max(0, (packet.valid_until - c.now()).total_seconds())):
            q = StockQuote.model_validate(
                (await c.stock_refresh(p.instrument)).model_dump(warnings=False)
            )
    except Exception:  # noqa: BLE001 -- failed reader cannot bypass independent protection
        q = None
    evidence["management"] = await c.engine.protective_stock_tick(q, now=c.now())
    if (
        result.error is not None
        or not evidence["position_timely"]
        or result.counted_input_tokens != result.usage.input_tokens
        or result.usage.input_tokens > config.limits.max_input_tokens
        or result.usage.output_tokens > config.limits.max_output_tokens
        or evidence["management"].get("status") != "HEALTHY"
    ):
        return c._finish(
            key, {**evidence, "status": "HELD", "reason": "STOCK_POSITION_MODEL_REJECTED"}
        )
    applied = apply(c, key, request, result, q, c.now())
    evidence["position_action"] = applied
    if applied["status"] != "PREPARED":
        return c._finish(key, {**evidence, "status": applied["status"]})
    status = await c.engine.dispatch_stock(applied["client_id"], q, now=c.now())
    if status == "REJECTED":
        evidence["management"] = await c.engine.protective_stock_tick(q, now=c.now())
    return c._finish(key, {**evidence, "status": status, "client_id": applied["client_id"]})
