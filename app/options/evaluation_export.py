"""Read-only first-session exports from native PAPER journals, without authority attachment."""

from datetime import datetime, timedelta
from decimal import Decimal

from app.execution.economics import UsageEvidence
from app.options.coordinator import DegenFrame
from app.options.engine import clock, exact, fingerprint
from app.options.evaluation import MAX_BUNDLE_BYTES, evaluate
from app.options.evaluation_models import (
    ArmDefinition,
    ArmSession,
    BenchmarkSession,
    EvaluationBundle,
    EvaluationManifest,
    ReplayCall,
    ReplayCycle,
    ReplayOrder,
)
from app.options.lifecycle import (
    OptionExecutionPolicy,
    OptionFill,
    OptionIntent,
    OptionLedger,
    OptionObservation,
    OptionReceipt,
    OptionVenueSnapshot,
)
from app.options.market_tape import RecordedTape
from app.options.models import OptionLimits
from app.options.observer import REQUIRED, OptionObserver, _json

MAX_EVENTS = 10000


def strategy_hash(strategy):
    """Bind strategy configuration without exporting the private model-key path."""
    content = {k: v for k, v in strategy.items() if k != "model"}
    if "model" in strategy:
        content["model"] = {"configuration": strategy["model"]["configuration"]}
    return fingerprint(content)


def _rows(db, table, bound):
    # Table names are fixed at the call sites, never supplied by source data.
    rows = db.execute(f"SELECT * FROM {table} LIMIT ?", (bound + 1,)).fetchall()
    if len(rows) > bound:
        raise ValueError("Native export record capacity exceeded")
    return rows


def _at(value):
    return clock(datetime.fromisoformat(value))


def _event_map(events, kind, key):
    result = {}
    for e in events:
        if e["kind"] != kind:
            continue
        payload = _json(e["payload"])
        identity = e["client_id"] if key == "client_id" else payload[key]
        if identity in result:
            raise ValueError("Duplicate native evidence event")
        result[identity] = (e, payload)
    return result


@exact
def export_arm(journal, definition, session, tape, *, data_cost=None, host_cost=None):
    """Export a journal's first session only; never reset or guess opening balances.

    Missing scheduler slots/unknown attempts stay incomplete. Structural conflicts
    fail export. There is no write, venue read, recovery or authority-file attachment.
    """
    definition = ArmDefinition.model_validate(definition.model_dump(warnings=False))
    tape = RecordedTape.model_validate(tape.model_dump(warnings=False))
    from app.options.evaluation_models import EvaluationSession

    session = EvaluationSession.model_validate(session.model_dump(warnings=False))
    h = tape.header
    if (session.key, session.opens_at, session.closes_at, session.tape_hash) != (
        h.session_key,
        h.opens_at,
        h.closes_at,
        tape.digest,
    ):
        raise ValueError("Exact session tape required")
    if definition.limits.model_dump(exclude={"account_id", "population_id"}) != h.limits.model_dump(
        exclude={"account_id", "population_id"}
    ):
        raise ValueError("Native limits and tape mismatch")
    observer = OptionObserver(journal, definition.limits.population_id)
    with observer.read() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED | {"execution_option_strategy", "execution_option_opportunities"} <= tables:
            raise ValueError("Existing native options strategy journal required")
        control = db.execute("SELECT * FROM execution_control WHERE id=1").fetchone()
        config = _json(control["config_json"])
        if (
            config["schema"] != "option-paper-execution-v1"
            or OptionLimits.model_validate(config["limits"]) != definition.limits
            or OptionExecutionPolicy.model_validate(config["policy"]) != definition.policy
        ):
            raise ValueError("Frozen native population definition mismatch")
        strategy = _json(
            db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
        )
        if (
            strategy_hash(strategy) != definition.strategy_hash
            or strategy["setup"] != h.setup.model_dump(mode="json")
            or strategy["selection"] != h.selection.model_dump(mode="json")
            or ("model" in strategy) != (definition.arm != "A")
            or ("entry_model" in strategy) != (definition.arm == "C")
        ):
            raise ValueError("Native A/B/C strategy binding mismatch")
        events = sorted(_rows(db, "execution_events", MAX_EVENTS), key=lambda e: e["sequence"])
        if any(e["sequence"] != n for n, e in enumerate(events, 1)):
            raise ValueError("Native event sequence incomplete")
        usage_events = _event_map(events, "OPTION_MODEL_USAGE_RECORDED", "source_key")
        admitted = _event_map(events, "OPTION_MODEL_ATTEMPT_ADMITTED", "source_key")
        attempts = _event_map(events, "OPTION_ATTEMPT_STARTED", "client_id")
        starts = _event_map(events, "DEGEN_CYCLE_STARTED", "cycle_key")
        finishes = _event_map(events, "DEGEN_CYCLE_COMPLETED", "cycle_key")
        calls = []
        model_rows = _rows(db, "execution_model_calls", 100)
        if {r["source_key"] for r in model_rows} != set(admitted) or not set(usage_events) <= set(
            admitted
        ):
            raise ValueError("Native model attempt coverage mismatch")
        for r in model_rows:
            key = r["source_key"]
            e, p = admitted[key]
            if e["occurred_at"] != r["started_at"] or p["input_hash"] != r["packet_hash"]:
                raise ValueError("Native model admission mismatch")
            usage, completed = None, None
            if key in usage_events:
                e, p = usage_events[key]
                usage = UsageEvidence.model_validate(_json(r["usage_json"]))
                policy = definition.policy.cost_policy
                if policy is None:
                    raise ValueError("Unexpected model cost")
                cost = (
                    usage.input_tokens * policy.input_per_million
                    + usage.output_tokens * policy.output_per_million
                ) / 1000000
                if (
                    usage.model_dump(mode="json") != p["usage"]
                    or usage.request_id != r["request_id"]
                    or usage.model != policy.model
                    or Decimal(r["cost"]) != cost
                    or Decimal(p["cost"]) != cost
                ):
                    raise ValueError("Native model receipt/cost mismatch")
                completed = _at(e["occurred_at"])
            elif any(
                r[k] is not None for k in ("usage_json", "request_id", "decision_hash", "cost")
            ):
                raise ValueError("Native model completion event missing")
            calls.append(
                ReplayCall(
                    source_key=key,
                    started_at=_at(r["started_at"]),
                    completed_at=completed,
                    usage=usage,
                )
            )
        orders, observed_fills = [], {}
        order_rows = _rows(db, "execution_orders", 200)
        if {r["client_id"] for r in order_rows if r["attempted_at"] is not None} != set(attempts):
            raise ValueError("Native order attempt coverage mismatch")
        for r in order_rows:
            intent = OptionIntent.model_validate(_json(r["intent_json"]))
            obs = (
                OptionObservation.model_validate(_json(r["observation_json"]))
                if r["observation_json"]
                else None
            )
            if intent.client_id != r["client_id"] or intent.source_key != r["source_key"]:
                raise ValueError("Native order identity mismatch")
            if (
                r["attempted_at"] is not None
                and attempts[intent.client_id][0]["occurred_at"] != r["attempted_at"]
            ):
                raise ValueError("Native attempt time mismatch")
            decision = intent.prepared_at
            if intent.side == "BUY" and definition.arm != "A":
                call = next((c for c in calls if c.source_key == intent.source_key), None)
                if call is None or call.completed_at is None:
                    raise ValueError("Native entry completion missing")
                decision = call.completed_at
            if obs:
                if r["order_id"] != obs.order_id or r["status"] != obs.status:
                    raise ValueError("Native order observation mismatch")
                for f in obs.fills:
                    if f.fill_id in observed_fills:
                        raise ValueError("Duplicate native fill")
                    observed_fills[f.fill_id] = (intent.client_id, f)
            orders.append(
                ReplayOrder(
                    intent=intent,
                    decision_completed_at=decision,
                    attempted_at=_at(r["attempted_at"]) if r["attempted_at"] else None,
                    observation=obs,
                )
            )
        stored_fills = {
            r["fill_id"]: (r["client_id"], OptionFill.model_validate(_json(r["payload"])))
            for r in _rows(db, "execution_fills", 1000)
        }
        if stored_fills != observed_fills:
            raise ValueError("Native fill-table coverage mismatch")
        receipt_rows = _rows(db, "execution_option_receipts", 200)
        receipts = tuple(OptionReceipt.model_validate(_json(r["payload"])) for r in receipt_rows)
        if any(
            r["receipt_id"] != receipt.receipt_id
            for r, receipt in zip(receipt_rows, receipts, strict=True)
        ):
            raise ValueError("Native receipt identity mismatch")
        cycle_rows = _rows(db, "execution_option_opportunities", 100)
        if {r["cycle_key"] for r in cycle_rows} != set(starts) or not set(finishes) <= set(starts):
            raise ValueError("Native scheduler event coverage mismatch")
        cycles = []
        call_keys = {c.source_key for c in calls}
        for r in cycle_rows:
            key, at = r["cycle_key"], _at(r["started_at"])
            frame = DegenFrame.model_validate(_json(r["inputs_json"]))
            if (
                key != "degen:" + str(int(at.timestamp()) // 300)
                or not session.opens_at <= at < session.closes_at
                or r["fingerprint"] != fingerprint(frame)
                or starts[key][1]["input_hash"] != fingerprint(frame)
                or starts[key][0]["occurred_at"] != r["started_at"]
            ):
                raise ValueError("Native cycle binding or first-session scope mismatch")
            outcome = _json(r["result_json"]) if r["result_json"] else {}
            if any(k in outcome for k in ("model_result", "entry_result")) and key not in call_keys:
                raise ValueError("Retained native model result has no charged or unknown attempt")
            if r["status"] == "COMPLETE":
                if key not in finishes or finishes[key][1] != outcome:
                    raise ValueError("Native cycle completion mismatch")
                status = outcome.get("status")
                status = (
                    status
                    if status in {"HOLD", "REJECTED", "ERROR", "OPEN", "HELD", "SKIPPED"}
                    else "UNKNOWN"
                )
            else:
                status = "UNKNOWN"
            call = next((c for c in calls if c.source_key == key), None)
            missed = bool(
                call
                and call.completed_at
                and int(call.completed_at.timestamp()) // 300 != int(at.timestamp()) // 300
            )
            cycles.append(
                ReplayCycle(
                    key=key,
                    frame_hash=fingerprint(frame),
                    status=status,
                    model_called=key in call_keys,
                    deadline_missed=missed,
                )
            )
        if not call_keys <= {c.key for c in cycles}:
            raise ValueError("Native model call has no retained cycle")
        if (
            any(not session.opens_at <= o.intent.prepared_at < session.closes_at for o in orders)
            or any(not session.opens_at <= c.started_at < session.closes_at for c in calls)
            or any(not session.opens_at <= r.occurred_at <= session.closes_at for r in receipts)
        ):
            raise ValueError("Export requires first-session history without a capital reset")
        closing = OptionLedger.model_validate(_json(control["ledger_json"]))
        snapshot = (
            OptionVenueSnapshot.model_validate(_json(control["snapshot_json"]))
            if control["snapshot_json"]
            else None
        )
        complete = bool(
            snapshot
            and snapshot.complete
            and session.closes_at
            <= snapshot.captured_at
            <= session.closes_at + timedelta(seconds=5)
            and not snapshot.underlying_exposures
            and not _json(control["issues_json"])
        )
        if snapshot and (
            snapshot.population_id != definition.limits.population_id
            or snapshot.account_id != definition.limits.account_id
            or snapshot.venue_id != config["venue_id"]
            or snapshot.cash != closing.cash
            or snapshot.settled_cash != closing.settled_cash
        ):
            raise ValueError("Native closing snapshot mismatch")
        if snapshot:
            observed = {o.intent.client_id: o.observation for o in orders if o.observation}
            if {o.client_id: o for o in snapshot.orders} != observed or {
                r.receipt_id: r for r in snapshot.receipts
            } != {r.receipt_id: r for r in receipts}:
                complete = False
            excluded = {
                "tightened_underlying_invalidation",
                "exit_reason",
                "exit_required_at",
                "supervision_issue",
            }
            position = lambda p: p.model_dump(exclude=excluded) if p else None
            if position(snapshot.position) != position(closing.position):
                raise ValueError("Native closing ownership mismatch")
        row = ArmSession(
            arm=definition.arm,
            session_key=session.key,
            definition_hash=fingerprint(definition),
            tape_hash=tape.digest,
            initial=OptionLedger(
                cash=definition.policy.capital, high_watermark=definition.policy.capital
            ),
            closing=closing,
            closing_complete=complete,
            orders=tuple(orders),
            receipts=receipts,
            calls=tuple(calls),
            cycles=tuple(cycles),
            data_cost=data_cost,
            host_cost=host_cost,
        )
        proof = {
            "arm": definition.arm,
            "revision": events[-1]["sequence"] if events else 0,
            "strategy_hash": strategy_hash(strategy),
            "export_hash": fingerprint(row),
            "execution_authority": False,
            "source_kind": "READ_ONLY_NATIVE_FIXTURE_JOURNAL",
        }
    return row, proof


def export_comparison(manifest, tape, sources):
    """Read three independent first-session sources and return an evaluator-ready bundle.

    sources maps A/B/C to {journal, data_cost, host_cost}; costs never default to zero.
    """
    manifest = EvaluationManifest.model_validate(manifest.model_dump(warnings=False))
    tape = RecordedTape.model_validate(tape.model_dump(warnings=False))
    if len(manifest.sessions) != 1 or set(sources) != {"A", "B", "C"}:
        raise ValueError("Exactly one first session and three independent sources required")
    rows, proof = [], []
    for definition in manifest.arms:
        source = sources[definition.arm]
        row, evidence = export_arm(
            source["journal"],
            definition,
            manifest.sessions[0],
            tape,
            data_cost=source.get("data_cost"),
            host_cost=source.get("host_cost"),
        )
        rows.append(row)
        proof.append(evidence)
    h = tape.header
    spy = [q for e in tape.events for q in e.frame.underlyings if q.symbol == "SPY"]
    starts = [q for q in spy if 0 <= (q.source_at - h.opens_at).total_seconds() <= 5]
    ends = [q for q in spy if 0 <= (h.closes_at - q.source_at).total_seconds() <= 5]
    benchmarks = ()
    if starts and ends:
        benchmarks = (
            BenchmarkSession(
                session_key=h.session_key,
                start=min(starts, key=lambda q: q.source_at),
                end=max(ends, key=lambda q: q.source_at),
            ),
        )
    bundle = EvaluationBundle(manifest=manifest, evidence=tuple(rows), benchmarks=benchmarks)
    if len(bundle.model_dump_json().encode()) > MAX_BUNDLE_BYTES:
        raise ValueError("Native export capacity exceeded")
    return {"bundle": bundle, "source_proof": proof, "report": evaluate(bundle, tapes=(tape,))}
