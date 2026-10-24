"""Pure cash-conserving paired session replay. Never opens an owner or calls a provider."""

from collections import Counter
from datetime import timedelta
from decimal import Context, Decimal, localcontext

from app.options.accounting import apply_fill, apply_receipt
from app.options.engine import fingerprint
from app.options.evaluation_models import EvaluationBundle
from app.options.fill_evidence import validate_fill
from app.options.lifecycle import TERMINAL, OptionLedger
from app.options.session_analysis import session_analysis

MAX_BUNDLE_BYTES = 16 * 1024 * 1024
ZERO = Decimal(0)


def _economic(ledger):
    from app.options.premium_trail import accounting_position

    # Management annotations do not alter accounting; exact ownership/protection does.
    data = ledger.model_dump()
    if ledger.position:
        data["position"] = accounting_position(
            ledger.position,
            {
                "tightened_underlying_invalidation",
                "exit_reason",
                "exit_required_at",
                "supervision_issue",
                "target_exit_stage",
            },
        )
    return data


def _replay(a, definition, session, sequence, used_ids, previous_close):
    events, quote_usage, active, turnover = [], {}, 0, ZERO
    previous_order_end = session.opens_at
    for order in sorted(a.orders, key=lambda x: x.attempted_at or x.intent.prepared_at):
        i, o = order.intent, order.observation
        from app.options.protection import verify_time_owner
        from app.options.swing_execution import verify_portable

        verify_portable(i, definition.policy)
        verify_time_owner(
            i, definition.policy, min(session.closes_at, i.instrument.contract.last_trading_at)
        )
        if (
            i.target_exit_schedule is not None
            and i.target_exit_schedule.needs_entry_reference
            and definition.policy.target_entry_reference is None
        ):
            raise ValueError("TARGET_ENTRY_REFERENCE_NOT_ENROLLED")
        if i.side == "BUY" and i.health_management != definition.policy.health_management:
            raise ValueError("HEALTH_MANAGEMENT_POLICY_MISMATCH")
        if i.side == "BUY" and i.premium_trail != definition.policy.premium_trail:
            raise ValueError("PREMIUM_TRAIL_POLICY_MISMATCH")
        if i.side == "BUY" and i.trade_floor != definition.policy.trade_floor:
            raise ValueError("TRADE_FLOOR_POLICY_MISMATCH")
        identity = ("client", i.client_id)
        if identity in used_ids:
            raise ValueError("DUPLICATE_ORDER")
        used_ids.add(identity)
        if ("source", i.source_key) in used_ids:
            raise ValueError("DUPLICATE_ORDER_SOURCE")
        used_ids.add(("source", i.source_key))
        if not session.opens_at <= order.decision_completed_at <= i.prepared_at < session.closes_at:
            raise ValueError("ORDER_OUTSIDE_SESSION_OR_BEFORE_DECISION")
        if (
            i.side == "BUY" and definition.policy.cost_policy is not None
        ) or i.position_protection is not None:
            call = next((c for c in a.calls if c.source_key == i.source_key), None)
            if (
                call is None
                or call.completed_at is None
                or call.completed_at > order.decision_completed_at
            ):
                raise ValueError("ENTRY_MODEL_COMPLETION_MISSING_OR_LATE")
        if order.attempted_at is None:
            if o is not None:
                raise ValueError("UNATTEMPTED_OBSERVATION")
            active += 1
            continue
        if (
            not i.prepared_at <= order.attempted_at < min(i.approval_expires_at, session.closes_at)
            or order.attempted_at < previous_order_end
        ):
            raise ValueError("ATTEMPT_LIFETIME_OR_OVERLAP")
        if o is None:
            active += 1
            previous_order_end = session.closes_at
            continue
        if ("order", o.order_id) in used_ids:
            raise ValueError("DUPLICATE_ORDER_RECEIPT")
        used_ids.add(("order", o.order_id))
        if (
            any(
                getattr(i, k) != getattr(o, k)
                for k in ("client_id", "instrument", "side", "quantity", "limit_price")
            )
            or not order.attempted_at <= o.updated_at <= session.closes_at
        ):
            raise ValueError("ORDER_OBSERVATION_MISMATCH")
        active += o.status not in TERMINAL
        previous_order_end = o.updated_at if o.status in TERMINAL else session.closes_at
        paid = ZERO
        for index, f in enumerate(o.fills):
            if ("fill", f.fill_id) in used_ids:
                raise ValueError("DUPLICATE_FILL")
            used_ids.add(("fill", f.fill_id))
            if (
                not order.attempted_at <= f.occurred_at <= o.updated_at
                or f.occurred_at >= i.order_expires_at
                or f.quote.source_at <= order.decision_completed_at
            ):
                raise ValueError("FILL_NOT_SUBSEQUENT_TO_DECISION_OR_EXPIRED")
            validate_fill(definition.limits, i, f, index, quote_usage)
            paid += f.quantity * f.price * i.instrument.contract.multiplier + f.fee
            turnover += f.quantity * f.price * i.instrument.contract.multiplier
            events.append((f.sequence, f.occurred_at, "FILL", (i, f)))
        if i.side == "BUY" and paid > i.approved_entry_debit:
            raise ValueError("APPROVED_DEBIT_EXCEEDED")
    for r in a.receipts:
        if ("receipt", r.receipt_id) in used_ids:
            raise ValueError("DUPLICATE_RECEIPT")
        used_ids.add(("receipt", r.receipt_id))
        if not session.opens_at <= r.occurred_at <= session.closes_at and not (
            previous_close is not None
            and r.kind == "FUNDS_SETTLED"
            and previous_close < r.occurred_at < session.opens_at
        ):
            raise ValueError("RECEIPT_OUTSIDE_SESSION")
        events.append((r.sequence, r.occurred_at, "RECEIPT", r))
    state, last_at = a.initial, previous_close or session.opens_at
    for seq, at, kind, event in sorted(events, key=lambda e: e[0]):
        if seq != sequence + 1 or at < last_at:
            raise ValueError("INCOMPLETE_OR_REGRESSING_EVENT_SEQUENCE")
        state = apply_fill(state, *event) if kind == "FILL" else apply_receipt(state, event)
        sequence, last_at = seq, at
    if _economic(state) != _economic(a.closing):
        raise ValueError("CASH_OR_OWNERSHIP_REPLAY_MISMATCH")
    return sequence, active, turnover


def _costs(a, definition, session, used_ids, prior_orders=()):
    known, unknown = ZERO, 0
    by_role = {r: {"known_cost": ZERO, "unknown_calls": 0} for r in ("ENTRY", "MANAGEMENT")}
    calls = {c.source_key: c for c in a.calls}
    if len(calls) != len(a.calls) or set(calls) != {c.key for c in a.cycles if c.model_called}:
        raise ValueError("MODEL_ATTEMPT_COVERAGE_MISMATCH")
    for cycle in a.cycles:
        attr = cycle.attribution
        if attr is None:
            if definition.arm == "D":
                raise ValueError("MANAGED_ATTRIBUTION_MISSING")
            continue
        call = calls.get(cycle.key)
        order = next((o for o in a.orders if o.intent.source_key == cycle.key), None)
        if attr.source_key != cycle.key or attr.model_attempted != (call is not None):
            raise ValueError("ATTRIBUTION_ATTEMPT_MISMATCH")
        if call and ((attr.role == "MANAGEMENT") != (call.role == "MANAGEMENT")):
            raise ValueError("ATTRIBUTION_COST_ROLE_MISMATCH")
        if attr.role == "MANAGEMENT" and definition.arm != "D":
            raise ValueError("UNENROLLED_MANAGEMENT_ATTRIBUTION")
        if attr.client_id != (order.intent.client_id if order else None):
            raise ValueError("ATTRIBUTION_ORDER_MISMATCH")
        fills = order.observation.fills if order and order.observation else ()
        if attr.fill_ids != tuple(f.fill_id for f in fills) or attr.filled_quantity != sum(
            f.quantity for f in fills
        ):
            raise ValueError("ATTRIBUTION_FILL_MISMATCH")
        from app.options.attribution import fill_underlying_observation

        if tuple(o.model_dump(mode="json") for o in attr.fill_underlyings) != tuple(
            fill_underlying_observation(f) for f in fills if f.underlying is not None
        ):
            raise ValueError("ATTRIBUTION_FILL_UNDERLYING_MISMATCH")
        entry = order
        if (order and order.intent.side == "SELL") or attr.role == "MANAGEMENT":
            entry = next(
                (
                    o
                    for o in (*prior_orders, *a.orders)
                    if o.intent.client_id == attr.entry_client_id
                ),
                None,
            )
            if entry is None or entry.intent.side != "BUY":
                raise ValueError("ATTRIBUTION_ORIGINAL_ENTRY_MISSING")
        if attr.swing_carry != (entry.intent.swing_carry if entry else None):
            raise ValueError("ATTRIBUTION_SWING_CARRY_MISMATCH")
        if (order or attr.entry_time_protection) and attr.entry_time_protection != (
            entry.intent.entry_time_protection if entry else None
        ):
            raise ValueError("ATTRIBUTION_ENTRY_TIME_MISMATCH")
        if order and (
            attr.approved_quantity != order.intent.quantity
            or attr.attempted != (order.attempted_at is not None)
        ):
            raise ValueError("ATTRIBUTION_APPROVAL_MISMATCH")
        if call and call.usage is not None and call.completed_at is not None:
            rates = definition.policy.cost_policy
            if (
                rates is None
                or attr.model_cost
                != (
                    call.usage.input_tokens * rates.input_per_million
                    + call.usage.output_tokens * rates.output_per_million
                )
                / 1000000
            ):
                raise ValueError("ATTRIBUTION_COST_MISMATCH")
        elif attr.model_cost is not None:
            raise ValueError("ATTRIBUTION_UNKNOWN_COST_MISMATCH")
    for call in a.calls:
        if ("call", call.source_key) in used_ids:
            raise ValueError("DUPLICATE_MODEL_ATTEMPT")
        used_ids.add(("call", call.source_key))
        policy = definition.policy.cost_policy
        if (
            (call.role == "MANAGEMENT" and definition.arm != "D")
            or policy is None
            or not session.opens_at <= call.started_at < session.closes_at
        ):
            raise ValueError("MODEL_ATTEMPT_POLICY_OR_TIME_MISMATCH")
        if call.usage is None or call.completed_at is None:
            unknown += 1
            by_role[call.role]["unknown_calls"] += 1
            continue
        usage = call.usage
        if not call.started_at <= call.completed_at or usage.model != policy.model:
            unknown += 1
            by_role[call.role]["unknown_calls"] += 1
            continue
        if ("response", usage.request_id) in used_ids:
            raise ValueError("DUPLICATE_MODEL_RECEIPT")
        used_ids.add(("response", usage.request_id))
        charge = (
            usage.input_tokens * policy.input_per_million
            + usage.output_tokens * policy.output_per_million
        ) / 1000000
        known += charge
        by_role[call.role]["known_cost"] += charge
    return (
        known,
        unknown,
        {
            r: {"known_cost": str(v["known_cost"]), "unknown_calls": v["unknown_calls"]}
            for r, v in by_role.items()
        },
    )


def _benchmark(value, session, source):
    if value is None:
        return None
    start, end = value.start, value.end
    for q in (start, end):
        if (
            q.symbol != "SPY"
            or q.source != source
            or q.entitlement != "REALTIME"
            or not q.complete
            or q.bid <= 0
            or q.bid > q.ask
            or not 0 <= (q.received_at - q.source_at).total_seconds() <= 5
        ):
            return None
    if (
        not 0 <= (start.source_at - session.opens_at).total_seconds() <= 5
        or not 0 <= (session.closes_at - end.source_at).total_seconds() <= 5
    ):
        return None
    return (end.bid + end.ask) / (start.bid + start.ask) - 1


def evaluate(bundle, *, tapes=None):
    """Replay supplied immutable evidence. Hashes bind content, not provider truth."""
    bundle = EvaluationBundle.model_validate(bundle.model_dump(warnings=False))
    if len(bundle.model_dump_json().encode()) > MAX_BUNDLE_BYTES:
        raise ValueError("Evaluation evidence capacity exceeded")
    recorded = None
    if tapes is not None:
        from app.options.recorded_evaluation import tape_issues

        recorded = tape_issues(bundle, tapes)
    with localcontext(Context(prec=192)):
        return _evaluate(bundle, recorded, tapes)


def _evaluate(bundle, recorded=None, tapes=None):
    m = bundle.manifest
    evidence = {(a.session_key, a.arm): a for a in bundle.evidence}
    benchmarks = {b.session_key: b for b in bundle.benchmarks}
    sessions = {s.key for s in m.sessions}
    previous_arms = {a.arm for a in m.arms}
    if (
        len(evidence) != len(bundle.evidence)
        or len(benchmarks) != len(bundle.benchmarks)
        or any(k[0] not in sessions or k[1] not in previous_arms for k in evidence)
        or not set(benchmarks) <= sessions
    ):
        raise ValueError("Duplicate or unenrolled session evidence")
    previous = {
        a.arm: OptionLedger(cash=a.policy.capital, high_watermark=a.policy.capital) for a in m.arms
    }
    sequences = dict.fromkeys(previous, 0)
    used_ids = {arm: set() for arm in previous}
    rows = []
    previous_close = None
    previous_loss = dict.fromkeys(previous)
    prior_orders = {arm: [] for arm in previous}
    for s in m.sessions:
        expected = {
            "degen:" + str(t // 300)
            for t in range(int(s.opens_at.timestamp()), int(s.closes_at.timestamp()), 300)
        }
        spy = _benchmark(benchmarks.get(s.key), s, m.arms[0].limits.underlying_source)
        arms, frames = {}, {}
        for definition in m.arms:
            arm = definition.arm
            a = evidence.get((s.key, arm))
            reasons, net, known, unknown, turnover = [], None, None, None, None
            verified = False
            counts = {}
            cost_roles = None
            if a is None:
                reasons.append("MISSING_ARM_SESSION")
                previous[arm] = None
            else:
                try:
                    if a.definition_hash != fingerprint(definition) or a.tape_hash != s.tape_hash:
                        raise ValueError("DEFINITION_OR_TAPE_MISMATCH")
                    if previous[arm] is None or _economic(a.initial) != _economic(previous[arm]):
                        raise ValueError("CAPITAL_OR_SESSION_CONTINUITY_MISMATCH")
                    from app.options.loss_evidence import validate_loss_boundary

                    validate_loss_boundary(
                        a.loss_control,
                        definition.policy.loss_control,
                        s.closes_at + timedelta(seconds=5),
                        previous_loss[arm],
                    )
                    previous_loss[arm] = a.loss_control
                    sequences[arm], active, turnover = _replay(
                        a, definition, s, sequences[arm], used_ids[arm], previous_close
                    )
                    verified = True
                    known, unknown, cost_roles = _costs(
                        a, definition, s, used_ids[arm], prior_orders[arm]
                    )
                    prior_orders[arm].extend(a.orders)
                    cycle_map = {c.key: c.frame_hash for c in a.cycles}
                    if len(cycle_map) != len(a.cycles) or set(cycle_map) != expected:
                        reasons.append("INCOMPLETE_SCHEDULER_COVERAGE")
                    frames[arm] = cycle_map
                    counts = dict(Counter(c.status for c in a.cycles))
                    counts["deadline_missed"] = sum(c.deadline_missed for c in a.cycles)
                    if counts.get("UNKNOWN"):
                        reasons.append("UNRESOLVED_CYCLE")
                    if active or not a.closing_complete:
                        reasons.append("UNRESOLVED_ORDER_OR_CLOSING_EVIDENCE")
                    if a.initial.position or a.closing.position:
                        reasons.append("OPEN_BOUNDARY_POSITION_UNVALUED")
                    if any(c.completed_at and c.completed_at > s.closes_at for c in a.calls):
                        reasons.append("MODEL_COMPLETION_AFTER_SESSION")
                    if unknown:
                        reasons.append("MODEL_COST_UNKNOWN")
                    if a.data_cost is None or a.host_cost is None:
                        reasons.append("ALLOCATED_COST_UNKNOWN")
                    if not reasons:
                        net = a.closing.cash - a.initial.cash - known - a.data_cost - a.host_cost
                    previous[arm] = a.closing
                except (ValueError, ArithmeticError) as exc:
                    reasons.append(
                        str(exc) if type(exc) is ValueError else "REPLAY_VALIDATION_FAILED"
                    )
                    previous[arm] = None
            arms[arm] = {
                **(
                    {"stored_loss_control": a.loss_control.model_dump(mode="json")}
                    if a and a.loss_control is not None
                    else {}
                ),
                "status": "COMPLETE" if not reasons else "INCONCLUSIVE",
                "reasons": reasons,
                "net_change": str(net) if net is not None else None,
                "accounting_verified": verified,
                "venue_cash_change": str(a.closing.cash - a.initial.cash) if verified else None,
                "realized_price_pnl": str(a.closing.realized_pnl - a.initial.realized_pnl)
                if verified
                else None,
                "venue_fees": str(a.closing.fees_paid - a.initial.fees_paid) if verified else None,
                "allocated_data_cost": str(a.data_cost) if a and a.data_cost is not None else None,
                "allocated_host_cost": str(a.host_cost) if a and a.host_cost is not None else None,
                "known_model_cost": str(known) if known is not None else None,
                "unknown_model_calls": unknown,
                "model_cost_by_role": cost_roles,
                "turnover": str(turnover) if turnover is not None else None,
                "cycle_counts": counts,
            }
        paired = all(a["status"] == "COMPLETE" for a in arms.values())
        pair_reasons = list(recorded[s.key]) if recorded is not None else []
        if len(frames) != len(m.arms) or any(
            frames.get(a) != frames.get("A") for a in [d.arm for d in m.arms[1:]]
        ):
            pair_reasons.append("UNMATCHED_MARKET_FRAME_COVERAGE")
        if spy is None:
            pair_reasons.append("SPY_BOUNDARY_EVIDENCE_MISSING_OR_INVALID")
        if not paired:
            pair_reasons.append("INCOMPLETE_ARM_EVIDENCE")
        complete = not pair_reasons
        rows.append(
            {
                "session": s.key,
                "status": "COMPLETE" if complete else "INCONCLUSIVE",
                "reasons": pair_reasons,
                "arms": arms,
                "spy_price_return": str(spy) if spy is not None else None,
                "cash_price_return": "0",
                "management_net_difference_D_minus_C": str(
                    Decimal(arms["D"]["net_change"]) - Decimal(arms["C"]["net_change"])
                )
                if complete and "D" in arms
                else None,
                "paired_net_difference": {
                    a: str(Decimal(arms[a]["net_change"]) - Decimal(arms["A"]["net_change"]))
                    if complete
                    else None
                    for a in [d.arm for d in m.arms[1:]]
                },
            }
        )
        previous_close = s.closes_at
    from app.options.underlying_baseline import underlying_report

    underlying = underlying_report(bundle, tapes, recorded, rows)
    if m.underlying_baseline is not None:
        for row, baseline in zip(rows, underlying["sessions"], strict=True):
            if baseline["status"] != "COMPLETE":
                row["status"] = "INCONCLUSIVE"
                row["reasons"].append("INCOMPLETE_UNDERLYING_BASELINE")
                row["paired_net_difference"] = dict.fromkeys(row["paired_net_difference"])
                row["management_net_difference_D_minus_C"] = None
    complete = all(r["status"] == "COMPLETE" for r in rows)
    spy_factor = Decimal(1)
    if complete:
        for row in rows:
            spy_factor *= 1 + Decimal(row["spy_price_return"])
    totals = {}
    for arm in [d.arm for d in m.arms]:
        changes = [Decimal(r["arms"][arm]["net_change"]) for r in rows] if complete else []
        equity = peak = m.arms[0].policy.capital
        drawdown = ZERO
        for change in changes:
            equity += change
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        totals[arm] = {
            "net_change": str(sum(changes, ZERO)) if complete else None,
            "net_return": str(sum(changes, ZERO) / m.arms[0].policy.capital) if complete else None,
            "worst_session": str(min(changes)) if changes else None,
            "session_boundary_drawdown": str(drawdown) if complete else None,
            "net_excess_vs_eligible_underlying": str(
                (sum(changes, ZERO) - Decimal(underlying["net_change"])) / m.arms[0].policy.capital
            )
            if complete and m.underlying_baseline is not None
            else None,
            "net_excess_vs_spy_price": str(
                sum(changes, ZERO) / m.arms[0].policy.capital - (spy_factor - 1)
            )
            if complete
            else None,
        }
    enough = sum(r["status"] == "COMPLETE" for r in rows) >= m.minimum_sessions
    return {
        "version": m.version,
        "experiment_id": m.experiment_id,
        "manifest_hash": fingerprint(m),
        "evidence_hash": fingerprint(bundle),
        "mode": "OFFLINE_FIXTURE_EVALUATION",
        "execution_authority": False,
        "live_enabled": False,
        "network_calls": False,
        "market_evidence": "SEALED_LOCAL_FIXTURE_TAPES"
        if recorded is not None
        else "SUPPLIED_HASHES_ONLY",
        "recorded_market_verified": recorded is not None and not any(recorded.values()),
        "status": "COMPLETE_ARITHMETIC" if complete else "INCONCLUSIVE",
        "economic_conclusion": "INCONCLUSIVE",
        "planned_sessions": len(rows),
        "complete_paired_sessions": sum(r["status"] == "COMPLETE" for r in rows),
        "minimum_sessions_met": enough,
        "spy_session_compounded_price_return": str(spy_factor - 1) if complete else None,
        "eligible_underlying": underlying,
        "session_analysis": session_analysis(m, rows),
        "sessions": rows,
        "totals": totals,
        **(
            {"carry_accounting": carry_accounting(bundle, rows, recorded)}
            if any(a.policy.swing_carry for a in m.arms)
            else {}
        ),
        "mean_paired_net_difference": {
            arm: str(
                (Decimal(totals[arm]["net_change"]) - Decimal(totals["A"]["net_change"]))
                / len(rows)
            )
            if complete
            else None
            for arm in [d.arm for d in m.arms[1:]]
        },
        "hurdle_per_session": str(m.hurdle_per_session),
        "limitations": [
            "Supplied fixture evidence and declared enrollment, not authenticated provider truth",
            "Accounting replay, not strategy rerun, prospective evidence or broker fills",
            "Unknown sessions remain in the denominator; no complete-case profitability result",
            "Flat session boundaries only; no invented marks for open or unresolved exposure",
            "SPY midpoint price return excludes dividends and benchmark execution costs",
            "SPY session compounding excludes overnight gaps; this is not buy-and-hold total return",
            "Session-boundary drawdown only; no intraday drawdown or statistical significance",
            "Underlying-only baseline and arm D require explicit enrollment",
        ],
    }


def carry_accounting(bundle, rows, recorded):
    """Whole-period cash arithmetic; never mark open positions or compare gapless SPY."""
    result = {}
    evidence = {(e.session_key, e.arm): e for e in bundle.evidence}
    for definition in bundle.manifest.arms:
        arm = definition.arm
        slices = [r["arms"][arm] for r in rows]
        first = evidence.get((rows[0]["session"], arm))
        last = evidence.get((rows[-1]["session"], arm))
        reasons = sorted(
            {
                reason
                for s in slices
                for reason in s["reasons"]
                if reason != "OPEN_BOUNDARY_POSITION_UNVALUED"
            }
        )
        if first is None or last is None or first.initial.position or last.closing.position:
            reasons.append("OPEN_PERIOD_BOUNDARY_UNVALUED")
        if recorded is None or any(recorded.values()):
            reasons.append("RECORDED_MARKET_NOT_VERIFIED")
        if any(set(r["reasons"]) - {"INCOMPLETE_ARM_EVIDENCE"} for r in rows):
            reasons.append("INCOMPLETE_PAIRED_MARKET_EVIDENCE")
        net = None
        if not reasons:
            net = (
                last.closing.cash
                - first.initial.cash
                - sum(
                    (
                        Decimal(s["known_model_cost"])
                        + Decimal(s["allocated_data_cost"])
                        + Decimal(s["allocated_host_cost"])
                        for s in slices
                    ),
                    ZERO,
                )
            )
        result[arm] = {
            "status": "COMPLETE_ARITHMETIC" if not reasons else "INCONCLUSIVE",
            "reasons": reasons,
            "net_change": str(net) if net is not None else None,
            "known_model_cost": str(sum((Decimal(s["known_model_cost"]) for s in slices), ZERO))
            if all(s["known_model_cost"] is not None for s in slices)
            else None,
            "economic_conclusion": "INCONCLUSIVE",
            "benchmark_comparison": None,
        }
    return result
