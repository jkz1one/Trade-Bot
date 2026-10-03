from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal

from app.storage.repository import Repository


def shadow_history_report(repo: Repository, benchmark_symbol: str, limit: int) -> dict:
    """Describe observed decisions/costs without inventing hypothetical fills or alpha."""
    if not 1 <= limit <= 10000:
        raise ValueError("limit must be between 1 and 10000")
    rows = list(reversed(repo.recent_cycles(limit)))
    cycles = []
    actions = Counter()
    rejections = Counter()
    models = Counter()
    cost = Decimal("0")
    benchmark_samples = []
    for row in rows:
        decision = json.loads(row.decision_json)
        risk = json.loads(row.risk_json)
        execution = json.loads(row.execution_json)
        packet = json.loads(row.packet_json)
        evidence = repo.shadow_cycle_evidence(row.id)
        usage = evidence["model_usage"]
        if usage is not None:
            cost += Decimal(usage["estimated_cost"])
        # Older cycles stored failures in the execution message, before agent_error existed.
        agent_failed = bool(execution.get("agent_error")) or "agent failure (" in execution.get("message", "")
        actions[decision["action"]] += 1
        models[row.model_identifier] += 1
        rejections.update(risk.get("rejection_reasons", []))
        benchmark = next((c["quote"] for c in packet.get("candidates", [])
                          if c["quote"]["symbol"] == benchmark_symbol), None)
        if benchmark is not None:
            benchmark_samples.append({"cycle_id": row.id, "price": benchmark["last"],
                                      "quote_timestamp": benchmark["timestamp"]})
        cycles.append({
            "cycle_id": row.id, "timestamp": packet["as_of"],
            "model": row.model_identifier, "prompt_version": row.prompt_version,
            "action": decision["action"], "symbol": decision.get("symbol"),
            "risk_approved": risk["approved"],
            "rejection_reasons": risk.get("rejection_reasons", []),
            "agent_failed": agent_failed, "agent_error": execution.get("agent_error"),
            "review_error": execution.get("review_error"),
            "review_completed": execution.get("broker_review") is not None,
            "evidence_status": evidence["status"], "model_usage": usage,
        })
    benchmark_return = None
    if len(benchmark_samples) >= 2:
        first = Decimal(str(benchmark_samples[0]["price"]))
        last = Decimal(str(benchmark_samples[-1]["price"]))
        if first > 0:
            benchmark_return = str(last / first - 1)
    return {
        "status": "OK" if rows else "EMPTY", "mode": "SHADOW", "window_limit": limit,
        "cycle_count": len(cycles), "action_counts": dict(actions),
        "model_counts": dict(models), "rejection_counts": dict(rejections),
        "genuine_hold_count": sum(c["action"] == "HOLD" and not c["agent_failed"] for c in cycles),
        "agent_failure_count": sum(c["agent_failed"] for c in cycles),
        "review_failure_count": sum(bool(c["review_error"]) for c in cycles),
        "review_count": sum(c["review_completed"] for c in cycles),
        "linked_cycle_count": sum(c["evidence_status"] == "LINKED" for c in cycles),
        "usage_reported_cycle_count": sum(c["model_usage"] is not None for c in cycles),
        "window_reported_model_cost": str(cost),
        "database_model_cost_total": str(repo.model_cost_total()),
        "cost_note": "Window cost includes only usage explicitly linked to selected cycles; missing usage is unknown.",
        "benchmark": {
            "symbol": benchmark_symbol, "sample_count": len(benchmark_samples),
            "first": benchmark_samples[0] if benchmark_samples else None,
            "last": benchmark_samples[-1] if benchmark_samples else None,
            "raw_price_return_fraction": benchmark_return,
        },
        "strategy_pnl": None, "economic_pnl": None,
        "performance_note": "SHADOW does not submit orders or simulate fills; strategy/economic P&L and alpha are not established.",
        "cycles": cycles,
    }
