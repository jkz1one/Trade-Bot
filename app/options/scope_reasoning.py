"""Strict fixed-plan Scope evidence for the shared entry model; no authority."""

from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import fingerprint
from app.options.lifecycle import EntryTimeProtection
from app.options.models import (
    OptionAccount,
    OptionAdmission,
    OptionInstrument,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    OptionRecord,
    SessionWindow,
    UnderlyingObservation,
)
from app.options.scope_entry import ScopeEntryBinding
from app.options.scope_management import ScopeManagementReview
from app.options.scope_structure import ScopeGeometry
from app.options.scope_watch import ScopeWatchChoice


class ScopeReasoningEvidence(OptionRecord):
    binding: ScopeEntryBinding
    binding_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    choice: ScopeWatchChoice
    geometry: ScopeGeometry
    instrument: OptionInstrument
    quote: OptionQuote
    underlying: UnderlyingObservation
    proposal: OptionProposal
    admission: OptionAdmission
    management: ScopeManagementReview
    entry_time_protection: EntryTimeProtection
    account: OptionAccount
    effective_limits: OptionLimits
    session: SessionWindow
    execution_blockers: tuple[str, ...] = Field(max_length=0)
    authority: Literal[False] = False
    live_enabled: Literal[False] = False

    @model_validator(mode="after")
    def bound(self):
        b, a, m = self.binding, self.admission, self.management
        if (
            self.binding_hash != fingerprint(b)
            or self.instrument != self.quote.instrument
            or self.proposal.contract != self.instrument.contract
            or self.proposal.action != "OPEN_LONG"
            or self.proposal.underlying_invalidation != self.geometry.invalidation
            or self.choice.right != self.geometry.right
            or a.outcome != "APPROVED"
            or a.contract_id != self.instrument.contract.contract_id
            or a.approved_at != b.evaluated_at
            or a.valid_until != b.valid_until
            or self.account.population_id != b.population_id
            or self.account.account_id != b.account_id
            or self.effective_limits.population_id != b.population_id
            or self.effective_limits.account_id != b.account_id
            or m.geometry != self.geometry
            or m.admitted_quantity != a.quantity
            or m.admission_hash != fingerprint(a)
            or not m.passed
            or m.valid_until != b.valid_until
            or m.evaluated_at != b.evaluated_at
            or self.entry_time_protection.exit_by != self.session.closes_at
        ):
            raise ValueError("Exact fixed Scope plan and owned admission required")
        return self
