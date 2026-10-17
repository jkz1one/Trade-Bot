"""One trader sees virtual account state; Robinhood remains READ only."""

from __future__ import annotations

from datetime import timedelta
from time import perf_counter

from app.agent.trader import AgentRun, fail_closed_agent_run
from app.domain.models import Action, MarketPacket, TradeDecision
from app.experiment.ledger import PaperLedger
from app.experiment.storage import SyntheticStore
from app.robinhood.reconcile import reconcile_truth


class MissingModelUsage(RuntimeError):
    pass


def guarded_hold(reason):
    return AgentRun(
        TradeDecision(
            action=Action.HOLD,
            confidence=0,
            setup_quality=0,
            thesis="Deterministic synthetic account guard selected HOLD.",
            invalidation_reason="No new model proposal is permitted for this cycle.",
            why_now=reason,
        )
    )


async def synthetic_cycle(orchestrator, window, token):
    if window is None:
        raise ValueError("Synthetic runs require the persistent regular-session scheduler")
    repo, settings = orchestrator.repo, orchestrator.settings
    claim = repo.shadow_slot(window.key)
    if claim is None or claim.status != "CLAIMED" or claim.claim_token != token:
        raise RuntimeError("Synthetic run must own a scheduled claim before reads")
    store = SyntheticStore(repo.session_factory)
    model = orchestrator.agent.model_identifier
    config, state, revision = store.validate_profile(settings, model)
    ledger = PaperLedger(
        config, state, unaccounted_calls=store.unaccounted_calls(settings.synthetic_experiment_id)
    )
    store.begin_attempt(settings.synthetic_experiment_id, window.key, token)
    truth = await orchestrator.reads.truth()
    # Compare only actual broker/local ownership. Virtual positions never enter it.
    reconciliation = reconcile_truth(repo, truth)
    candidates = await orchestrator.market.candidates(
        truth.account.account_number, settings.initial_symbols
    )
    packet = MarketPacket(
        as_of=orchestrator.clock(),
        account=ledger.account(),
        candidates=candidates,
        regime=orchestrator.market.regime(candidates),
        session_context={
            **window.context(),
            "account_context": "SYNTHETIC_PAPER",
            "experiment_id": settings.synthetic_experiment_id,
            "execution_policy": config.policy,
        },
    )
    session_open = window.is_open(packet.as_of)
    if reconciliation.reconciled and session_open:
        ledger.prepare(packet, window)
    else:
        ledger.state.last_as_of = packet.as_of
        ledger.position_fresh = state.position is None
        ledger.events.append(
            "RECONCILIATION_FAILED" if not reconciliation.reconciled else "SESSION_BLOCKED"
        )
    packet = packet.model_copy(
        update={
            "account": ledger.account(),
            "recent_lessons": [
                "This is a separate synthetic PAPER bankroll, not Robinhood account ownership.",
                "Model intents wait for the next fresh scheduled quote and are revalidated. Original stops never widen.",
                "Cash/equity reserve reported model costs and assumed exit fees; unknown costs block new entries.",
            ],
        }
    )
    attempted = False
    model_latency_ms = 0
    if not reconciliation.reconciled:
        run = guarded_hold("Broker/local reconciliation failed; preserve the virtual ledger.")
    elif not ledger.ready or ledger.unknown_model_calls:
        run = guarded_hold(
            "Fresh account/benchmark marks, complete costs and no pending proposal are required."
        )
    elif window.scheduled_for + timedelta(minutes=15) >= window.closes_at:
        run = guarded_hold(
            "The last session slot has no later scheduled quote for a new model intent."
        )
    else:
        attempted = model != "stub"
        if attempted:
            store.mark_model_attempt(window.key, token)
        started = perf_counter()
        run = await orchestrator._decide(packet)
        model_latency_ms = int((perf_counter() - started) * 1000)
        if attempted and not run.error and not (run.input_tokens or run.output_tokens):
            run = fail_closed_agent_run(MissingModelUsage())
    usage = ledger.charge_model(run.input_tokens, run.output_tokens, attempted=attempted)
    completed = orchestrator.clock()
    risk = ledger.propose(run.decision, packet, completed, window, agent_error=run.error)
    execution = {
        "mode": "SYNTHETIC_PAPER",
        "status": "FILLED" if ledger.fills else "SKIPPED",
        "agent_error": run.error,
        "model_attempted": attempted,
        "model_latency_ms": model_latency_ms,
        "pending_created": ledger.state.pending is not None
        and ledger.state.pending.source_cycle_id is None,
        "reconciliation": reconciliation.model_dump(mode="json"),
        "risk_account": ledger.account().model_dump(mode="json"),
        "release_sha": settings.release_sha,
    }
    code = 3 if not reconciliation.reconciled else 8 if run.error else 0
    cycle_id = store.commit(
        settings.synthetic_experiment_id,
        revision,
        ledger,
        packet,
        run.decision,
        risk,
        execution,
        usage,
        model=model if attempted or model == "stub" else "session-guard",
        prompt_version=config.prompt_version,
        slot_key=window.key,
        claim_token=token,
        completed_at=completed,
        exit_code=code,
    )
    return {
        "mode": "SYNTHETIC_PAPER",
        "experiment_id": settings.synthetic_experiment_id,
        "synthetic_cycle_id": cycle_id,
        "decision": run.decision.model_dump(mode="json"),
        "risk": risk.model_dump(mode="json"),
        "execution": execution,
        "exit_code": code,
    }
