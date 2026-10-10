"""Candidate-first exact option reads and deterministic admission of a bounded set."""

from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.options.degen import DegenScan, Family
from app.options.governor import _fresh, _supported, admit_option
from app.options.models import (
    Evidence,
    Money,
    Name,
    OptionAdmission,
    OptionInstrument,
    OptionProposal,
    OptionRecord,
    Symbol,
)


class ContractSelectionPolicy(OptionRecord):
    version: Literal["degen-contract-selection-v1"] = "degen-contract-selection-v1"
    metadata_source: Name
    max_inventory_contracts: int = Field(gt=0, le=32, strict=True)
    max_quote_contracts: int = Field(gt=0, le=8, strict=True)
    max_metadata_age_seconds: int = Field(gt=0, le=60, strict=True)
    minimum_abs_delta: Money = Field(gt=0, lt=1)
    maximum_abs_delta: Money = Field(gt=0, le=1)
    target_abs_delta: Money = Field(gt=0, lt=1)
    maximum_strike_distance_fraction: Money = Field(gt=0, le=Decimal(".1"))
    minimum_volume: int = Field(ge=0, le=1_000_000_000, strict=True)
    minimum_open_interest: int = Field(ge=0, le=1_000_000_000, strict=True)

    @model_validator(mode="after")
    def coherent(self):
        if (
            not self.minimum_abs_delta <= self.target_abs_delta <= self.maximum_abs_delta
            or self.max_quote_contracts > self.max_inventory_contracts
        ):
            raise ValueError("A bounded coherent frozen contract selection policy is required")
        return self


class ContractMetadata(Evidence):
    instrument: OptionInstrument
    delta: Money | None = Field(default=None, ge=-1, le=1)
    greek_provenance: Literal["OBSERVED", "ESTIMATED", "UNAVAILABLE"]
    volume: int | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)
    open_interest: int | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)


class OptionInventory(Evidence):
    request_id: Name
    symbol: Symbol
    expiration: date
    contracts: tuple[ContractMetadata, ...] = Field(max_length=32)


class ContractReadPlan(OptionRecord):
    symbol: Symbol
    evaluated_at: datetime
    instruments: tuple[OptionInstrument, ...] = Field(max_length=8)
    exclusions: dict[Name, tuple[Name, ...]]
    issues: tuple[Name, ...] = ()


class DegenCandidate(OptionRecord):
    candidate_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    symbol: Symbol
    family: Family
    instrument: OptionInstrument
    proposal: OptionProposal
    admission: OptionAdmission


def plan_contract_reads(scan, inventory, policy, limits, *, now):
    scan = DegenScan.model_validate(scan.model_dump(warnings=False))
    inventory = OptionInventory.model_validate(inventory.model_dump(warnings=False))
    policy = ContractSelectionPolicy.model_validate(policy.model_dump(warnings=False))
    with localcontext(Context(prec=192)):
        return _plan(scan, inventory, policy, limits, now)


def _plan(scan, inventory, policy, limits, now):
    rights = {s.right for s in scan.observations if s.status == "CONFIRMED"}
    issues = []
    if scan.issues or not rights:
        issues.append("NO_CONFIRMED_SETUP")
    if scan.evaluated_at != now or scan.last_close is None or scan.completed_through is None:
        issues.append("SCAN_TIME_OR_STRUCTURE_MISMATCH")
    if (
        inventory.symbol != scan.symbol
        or inventory.expiration != now.astimezone(ZoneInfo("America/New_York")).date()
        or inventory.source != policy.metadata_source
        or not inventory.complete
        or inventory.entitlement != "REALTIME"
        or not _fresh(
            inventory.source_at,
            inventory.received_at,
            now,
            policy.max_metadata_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        issues.append("INVENTORY_BINDING_COVERAGE_OR_FRESHNESS")
    if len(inventory.contracts) > policy.max_inventory_contracts:
        issues.append("INVENTORY_CAPACITY_EXCEEDED")
    ids = [c.instrument.instrument_id for c in inventory.contracts]
    canonical = [c.instrument.contract.contract_id for c in inventory.contracts]
    if len(ids) != len(set(ids)) or len(canonical) != len(set(canonical)):
        issues.append("DUPLICATE_OR_CONFLICTING_CONTRACT_IDENTITY")
    if issues:
        return ContractReadPlan(
            symbol=scan.symbol,
            evaluated_at=now,
            instruments=(),
            exclusions={},
            issues=tuple(issues),
        )
    exclusions, ranked = {}, []
    for metadata in inventory.contracts:
        instrument, reasons = metadata.instrument, []
        c = instrument.contract
        if (
            instrument.provider != limits.provider
            or not instrument.metadata_complete
            or not instrument.option_tradable
            or not _supported(c)
            or c.underlying != inventory.symbol
            or c.root != inventory.symbol
            or c.expiration != inventory.expiration
            or c.right not in rights
            or now >= c.last_trading_at
        ):
            reasons.append("INSTRUMENT_OR_ZERO_DTE_IDENTITY_INELIGIBLE")
        if (
            metadata.source != policy.metadata_source
            or not metadata.complete
            or metadata.entitlement != "REALTIME"
            or not _fresh(
                metadata.source_at,
                metadata.received_at,
                now,
                policy.max_metadata_age_seconds,
                limits.max_receive_lag_seconds,
            )
        ):
            reasons.append("CONTRACT_METADATA_STALE_DELAYED_OR_INCOMPLETE")
        if metadata.greek_provenance != "OBSERVED" or metadata.delta is None:
            reasons.append("OBSERVED_DELTA_REQUIRED")
        elif not policy.minimum_abs_delta <= abs(metadata.delta) <= policy.maximum_abs_delta or (
            metadata.delta <= 0 if c.right == "CALL" else metadata.delta >= 0
        ):
            reasons.append("DELTA_RANGE_OR_DIRECTION_INELIGIBLE")
        if metadata.volume is None or metadata.volume < policy.minimum_volume:
            reasons.append("OPTION_VOLUME_UNAVAILABLE_OR_LOW")
        if metadata.open_interest is None or metadata.open_interest < policy.minimum_open_interest:
            reasons.append("OPEN_INTEREST_UNAVAILABLE_OR_LOW")
        if abs(c.strike / scan.last_close - 1) > policy.maximum_strike_distance_fraction:
            reasons.append("STRIKE_TOO_DISTANT")
        if reasons:
            exclusions[instrument.instrument_id] = tuple(reasons)
        else:
            ranked.append(
                (
                    abs(abs(metadata.delta) - policy.target_abs_delta),
                    abs(c.strike - scan.last_close),
                    c.contract_id,
                    instrument,
                )
            )
    ranked.sort(key=lambda x: x[:3])
    for _, _, _, instrument in ranked[policy.max_quote_contracts :]:
        exclusions[instrument.instrument_id] = ("OUTSIDE_FROZEN_QUOTE_CAPACITY",)
    return ContractReadPlan(
        symbol=scan.symbol,
        evaluated_at=now,
        instruments=tuple(x[3] for x in ranked[: policy.max_quote_contracts]),
        exclusions=exclusions,
        issues=() if ranked else ("NO_ELIGIBLE_METADATA",),
    )


def admit_candidates(scan, plan, quotes, underlying, account, limits, session, *, now):
    """This result is evidence. M2 re-admits the chosen fixed intent before attempt."""
    from app.options.engine import fingerprint
    from app.options.models import OptionQuote, UnderlyingQuote

    scan = DegenScan.model_validate(scan.model_dump(warnings=False))
    plan = ContractReadPlan.model_validate(plan.model_dump(warnings=False))
    quotes = tuple(OptionQuote.model_validate(q.model_dump(warnings=False)) for q in quotes)
    underlying = UnderlyingQuote.model_validate(underlying.model_dump(warnings=False))
    expected = {i.instrument_id: i for i in plan.instruments}
    actual = {q.instrument.instrument_id: q for q in quotes}
    if plan.issues or scan.issues or plan.evaluated_at != now or scan.evaluated_at != now:
        return (), {"selection": ("READ_PLAN_OR_SCAN_BLOCKED",)}
    if (
        len(actual) != len(quotes)
        or set(actual) != set(expected)
        or any(actual[k].instrument != i for k, i in expected.items())
    ):
        return (), {"selection": ("EXACT_REQUESTED_QUOTE_COVERAGE_REQUIRED",)}
    if underlying.symbol != scan.symbol:
        return (), {"selection": ("UNDERLYING_IDENTITY_MISMATCH",)}
    accepted, rejected = [], {}
    for setup in scan.observations:
        if setup.status != "CONFIRMED":
            continue
        for instrument in plan.instruments:
            if instrument.contract.right != setup.right:
                continue
            proposal = OptionProposal(
                action="OPEN_LONG",
                contract=instrument.contract,
                underlying_invalidation=setup.invalidation,
                thesis=f"Degen {setup.family}: completed 5m setup and 15m confirmation",
            )
            result = admit_option(
                proposal,
                actual[instrument.instrument_id],
                underlying,
                account,
                limits,
                session,
                now=now,
            )
            candidate_id = fingerprint(
                {
                    "scan": scan,
                    "instrument": instrument,
                    "family": setup.family,
                    "quote": actual[instrument.instrument_id],
                }
            )
            if result.outcome == "APPROVED":
                accepted.append(
                    DegenCandidate(
                        candidate_id=candidate_id,
                        symbol=scan.symbol,
                        family=setup.family,
                        instrument=instrument,
                        proposal=proposal,
                        admission=result,
                    )
                )
            else:
                rejected[candidate_id] = result.reasons
    return tuple(accepted), rejected
