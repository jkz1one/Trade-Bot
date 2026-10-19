"""Owned Scope management context; historical terms never become fresh admission."""

import json
from datetime import timedelta

from pydantic import model_validator

from app.options.entry_reasoning import SharedScopeEntryPlan
from app.options.models import OptionRecord
from app.options.scope_arbitration import ScopeCycleInput, configuration
from app.options.scope_context import ScopeContextPolicy, ScopeContextScan, scan_scope_context
from app.options.scope_reasoning import ScopeReasoningEvidence


class ScopePositionContext(OptionRecord):
    selection: SharedScopeEntryPlan
    original: ScopeReasoningEvidence
    current: ScopeCycleInput
    policy: ScopeContextPolicy
    scan: ScopeContextScan

    @model_validator(mode="after")
    def bound(self):
        f, s, o = self.current, self.scan, self.original
        if (
            self.selection.action != "ENTER"
            or not self.selection.scope
            or f.play_key != o.binding.play_key
            or f.frame.quote is None
            or f.frame.quote.instrument != o.instrument
            or f.underlying.symbol != o.instrument.contract.underlying
            or s != scan_scope_context(f.frame, f.context, self.policy, now=s.evaluated_at)
            or s.issues
            or s.structure.issues
            or s.structure.completed_through is None
            or not timedelta(0)
            <= s.evaluated_at - s.structure.completed_through
            < timedelta(seconds=300)
            or s.evaluated_at < o.binding.evaluated_at
        ):
            raise ValueError(
                "Exact Scope play, held contract and current completed context required"
            )
        return self


def owned_context(db, entry, current, *, now):
    """Verify the native entry and full paid selection before exposing its original terms."""
    from app.options.attribution import order_attribution
    from app.options.scope_ai import validate_stored
    from app.options.scope_execution import stored_entry

    policy = configuration(db)
    if policy.version != "shared-scope-entry-v1":
        raise ValueError("Shared Scope AI owner required")
    row = db.execute(
        "SELECT * FROM execution_orders WHERE client_id=?", (entry.client_id,)
    ).fetchone()
    if row is None or json.loads(row["intent_json"]) != entry.model_dump(mode="json"):
        raise ValueError("Stored Scope management entry changed")
    order_attribution(db, row)
    receipt = stored_entry(db, entry.source_key)
    if receipt is None or receipt["client_id"] != entry.client_id:
        raise ValueError("Exact native Scope entry required")
    approval = json.loads(row["approval_json"])
    key = approval["scope_arbitration"]["cycle_key"]
    evidence = json.loads(
        db.execute(
            "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
        ).fetchone()[0]
    )
    _, result = validate_stored(db, key, evidence, policy)
    return ScopePositionContext(
        selection=result.plan,
        original=ScopeReasoningEvidence.model_validate(receipt["packet"]),
        current=current,
        policy=policy.watch.context,
        scan=scan_scope_context(current.frame, current.context, policy.watch.context, now=now),
    )


def verify_owned_context(db, packet):
    if packet.scope_context is None:
        return
    context = packet.scope_context
    expected = owned_context(db, packet.entry, context.current, now=packet.as_of)
    if expected != context:
        raise ValueError("Stored Scope management context changed")
    # Full frozen management configuration is checked by the ordinary owner path.
    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    if (
        config.get("position_model", {}).get("position_policy", {}).get("scope_management")
        != "scope-fixed-position-v1"
    ):
        raise ValueError("Frozen Scope management enrollment required")
