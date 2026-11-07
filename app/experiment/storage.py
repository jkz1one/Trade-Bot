"""Atomic synthetic journal, isolated from real-account SHADOW evidence and ownership."""

from __future__ import annotations

import json
import re

from sqlalchemy import func, select, update

from app.experiment.ledger import ExperimentConfig, LedgerState
from app.storage.models import (
    ShadowScheduleSlotRow,
    SyntheticAttemptRow,
    SyntheticCycleRow,
    SyntheticExperimentRow,
    SyntheticFillRow,
)


def experiment_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("Experiment ID must contain 1-64 letters, digits, underscores or hyphens")
    return value


class SyntheticStore:
    def __init__(self, factory):
        self.factory = factory

    def initialize(self, name, config):
        name = experiment_id(name)
        state = LedgerState(
            cash=config.capital, high_watermark=config.capital, benchmark_cash=config.capital
        )
        with self.factory.begin() as session:
            if session.get(SyntheticExperimentRow, name) is not None:
                raise ValueError("An existing experiment cannot be reset or reconfigured")
            session.add(
                SyntheticExperimentRow(
                    id=name,
                    config_json=config.model_dump_json(),
                    state_json=state.model_dump_json(),
                    revision=0,
                )
            )

    def load(self, name):
        with self.factory() as session:
            row = session.get(SyntheticExperimentRow, experiment_id(name))
            if row is None:
                raise ValueError("Initialize the named synthetic experiment before selecting it")
            return (
                ExperimentConfig.model_validate_json(row.config_json),
                LedgerState.model_validate_json(row.state_json),
                row.revision,
            )

    def begin_attempt(self, name, slot_key, token):
        with self.factory.begin() as session:
            self._owned_attempt_slot(session, slot_key, token)
            session.add(SyntheticAttemptRow(slot_key=slot_key, experiment_id=name))

    @staticmethod
    def _owned_attempt_slot(session, key, token):
        slot = session.get(ShadowScheduleSlotRow, key)
        if slot is None or slot.status != "CLAIMED" or slot.claim_token != token:
            raise RuntimeError("Synthetic attempt must own its scheduled claim")
        return slot

    def mark_model_attempt(self, slot_key, token):
        with self.factory.begin() as session:
            self._owned_attempt_slot(session, slot_key, token)
            attempt = session.get(SyntheticAttemptRow, slot_key)
            if attempt is None or attempt.accounted:
                raise RuntimeError("Synthetic attempt receipt missing or already accounted")
            attempt.model_attempted = True

    @staticmethod
    def _unaccounted(session, name):
        return session.scalar(
            select(func.count())
            .select_from(SyntheticAttemptRow)
            .where(
                SyntheticAttemptRow.experiment_id == name,
                SyntheticAttemptRow.model_attempted.is_(True),
                SyntheticAttemptRow.accounted.is_(False),
            )
        )

    def unaccounted_calls(self, name):
        with self.factory() as session:
            return self._unaccounted(session, name)

    def validate_profile(self, settings, model):
        config, state, revision = self.load(settings.synthetic_experiment_id)
        expected = ExperimentConfig.capture(
            settings,
            model,
            capital=config.capital,
            slippage_bps=config.slippage_bps,
            fee_per_fill=config.fee_per_fill,
        )
        if config != expected:
            raise ValueError(
                "Synthetic model, pricing or risk policy changed; use a new experiment identity"
            )
        return config, state, revision

    def commit(
        self,
        name,
        revision,
        ledger,
        packet,
        decision,
        risk,
        execution,
        usage,
        *,
        model,
        prompt_version,
        slot_key,
        claim_token,
        completed_at,
        exit_code,
    ):
        if completed_at < packet.as_of:
            raise ValueError("Synthetic completion cannot precede its input")
        with self.factory.begin() as session:
            slot = session.get(ShadowScheduleSlotRow, slot_key)
            if slot is None or slot.status != "CLAIMED" or slot.claim_token != claim_token:
                raise RuntimeError("Synthetic cycle does not own the active scheduled claim")
            row = SyntheticCycleRow(
                experiment_id=name,
                slot_key=slot_key,
                timestamp=packet.as_of,
                completed_at=completed_at,
                model=model,
                prompt_version=prompt_version,
                packet_json=packet.model_dump_json(),
                decision_json=decision.model_dump_json(),
                risk_json=risk.model_dump_json(),
                execution_json=json.dumps(execution),
                usage_json=json.dumps(usage) if usage else None,
                snapshot_json="{}",
            )
            session.add(row)
            session.flush()
            if ledger.state.pending and ledger.state.pending.source_cycle_id is None:
                ledger.state.pending.source_cycle_id = row.id
            result = session.execute(
                update(SyntheticExperimentRow)
                .where(
                    SyntheticExperimentRow.id == name,
                    SyntheticExperimentRow.revision == revision,
                )
                .values(state_json=ledger.state.model_dump_json(), revision=revision + 1)
            )
            if result.rowcount != 1:
                raise RuntimeError("Synthetic state changed during judgment; transition rejected")
            row.snapshot_json = json.dumps(ledger.snapshot())
            for fill in ledger.fills:
                session.add(
                    SyntheticFillRow(
                        experiment_id=name,
                        cycle_id=row.id,
                        source_cycle_id=fill["source_cycle_id"],
                        fill_json=json.dumps(fill),
                    )
                )
            slot.status = "COMPLETED" if exit_code == 0 else "FAILED"
            slot.exit_code = exit_code
            slot.error_class = execution.get("agent_error")
            slot.finished_at = completed_at
            slot.active_lock = None
            # The common scheduler serializes all populations; its SHADOW FK must
            # never refer to a synthetic cycle. The synthetic journal links the slot.
            slot.cycle_id = None
            attempt = session.get(SyntheticAttemptRow, slot_key)
            if attempt is None or attempt.experiment_id != name or attempt.accounted:
                raise RuntimeError("Synthetic attempt receipt inconsistent with transition")
            attempt.accounted = True
            session.flush()
            return row.id

    def cycle_for_slot(self, slot_key):
        with self.factory() as session:
            row = session.scalar(
                select(SyntheticCycleRow).where(SyntheticCycleRow.slot_key == slot_key)
            )
            return {"experiment_id": row.experiment_id, "synthetic_cycle_id": row.id} if row else {}

    def report(self, name, limit=25):
        if not 1 <= limit <= 100:
            raise ValueError("Synthetic history limit must be between 1 and 100")
        with self.factory() as session:
            connection = session.connection()
            if (
                connection.dialect.name == "sqlite"
                and not connection.connection.driver_connection.in_transaction
            ):
                connection.exec_driver_sql("BEGIN")
            experiment = session.get(SyntheticExperimentRow, experiment_id(name))
            if experiment is None:
                raise ValueError("Synthetic experiment not found")
            config = ExperimentConfig.model_validate_json(experiment.config_json)
            state = LedgerState.model_validate_json(experiment.state_json)
            revision = experiment.revision
            unaccounted = self._unaccounted(session, name)
            rows = list(
                session.scalars(
                    select(SyntheticCycleRow)
                    .where(
                        SyntheticCycleRow.experiment_id == name,
                    )
                    .order_by(SyntheticCycleRow.id.desc())
                    .limit(limit)
                )
            )
            fills = list(
                session.scalars(
                    select(SyntheticFillRow)
                    .where(
                        SyntheticFillRow.experiment_id == name,
                    )
                    .order_by(SyntheticFillRow.id.desc())
                    .limit(limit)
                )
            )
        latest = json.loads(rows[0].snapshot_json) if rows else None
        if latest is not None and unaccounted:
            latest["unknown_model_calls"] = state.unknown_model_calls + unaccounted
            for key in (
                "net_after_model_cost_equity",
                "net_return_fraction",
                "net_excess_fraction",
                "max_drawdown_fraction",
            ):
                latest[key] = None
        return {
            "status": "OK" if rows else "EMPTY",
            "mode": "SYNTHETIC_PAPER",
            "experiment_id": name,
            "config": config.model_dump(mode="json"),
            "revision": revision,
            "latest": latest,
            "cycles": [
                {
                    "cycle_id": row.id,
                    "timestamp": row.timestamp.isoformat(),
                    "model": row.model,
                    "prompt_version": row.prompt_version,
                    "decision": json.loads(row.decision_json),
                    "risk": json.loads(row.risk_json),
                    "execution": json.loads(row.execution_json),
                    "usage": json.loads(row.usage_json) if row.usage_json else None,
                }
                for row in reversed(rows)
            ],
            "fills": [
                {"fill_id": row.id, "cycle_id": row.cycle_id, **json.loads(row.fill_json)}
                for row in reversed(fills)
            ],
            "known_model_cost": str(state.known_model_cost),
            "unknown_model_calls": state.unknown_model_calls + unaccounted,
            "unaccounted_model_attempts": unaccounted,
            "network_calls": False,
            "measurement_note": "Synthetic next-quote execution, never broker fills. Spread plus fixed slippage/fees; fractional quantities round down to 8 decimals. Marks reserve exit fees. SPY uses matching initial capital, start quotes and execution assumptions, without trader model costs. No dividends, splits, taxes, hosting or setup-call costs. Missing usage or stale position marks make net economics unavailable.",
        }

    def summaries(self):
        with self.factory() as session:
            names = list(
                session.scalars(
                    select(SyntheticExperimentRow.id).order_by(SyntheticExperimentRow.id).limit(10)
                )
            )
        return [self.report(name, 5) for name in names]


def annotate_tick(settings, repo, result):
    if settings.synthetic_experiment_id:
        result = {
            **result,
            "population": "SYNTHETIC_PAPER",
            "experiment_id": settings.synthetic_experiment_id,
        }
        if result.get("slot_key"):
            result.update(SyntheticStore(repo.session_factory).cycle_for_slot(result["slot_key"]))
    return result
