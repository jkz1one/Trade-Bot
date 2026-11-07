"""Order-free portfolio admission constraints; not native dispatch authority.

Inputs must be rebuilt from authoritative fills/reservations inside the owner's
write transaction. This module deliberately does not alter legacy enrollment.
"""

from decimal import Context, Decimal, localcontext
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.options.models import Money, Name, OptionRecord, Symbol

ZERO = Decimal(0)


class PlayCommitment(OptionRecord):
    """One original entry, including its held part and unfilled reservation.

    invested_loss excludes already charged fees; remaining_debit excludes paid
    fills. Exit reserve covers the held and still reserved entry quantity once.
    Exit orders retain their original play commitment until confirmed closed.
    """

    play_id: Name
    entry_client_id: Name
    instrument_id: Name
    underlying: Symbol
    family: Literal["DEGEN", "SWING", "SCOPE"]
    invested_loss: Money = Field(ge=0)
    remaining_debit: Money = Field(ge=0)
    exit_reserve: Money = Field(ge=0)
    has_position: StrictBool
    pending_entry: StrictBool
    uncertain: StrictBool = False

    @model_validator(mode="after")
    def occupied(self):
        if not self.has_position and not self.pending_entry:
            raise ValueError("Closed plays do not consume capacity")
        if not self.has_position and self.invested_loss:
            raise ValueError("Unfilled entries have no invested basis")
        if not self.pending_entry and self.remaining_debit:
            raise ValueError("Terminal entry cannot retain an unfilled debit")
        return self


class PortfolioCapacity(OptionRecord):
    version: Literal["mixed-portfolio-capacity-v1"] = "mixed-portfolio-capacity-v1"
    account_id: Name
    population_id: Name
    revision: StrictInt = Field(ge=0)
    max_plays: StrictInt = Field(ge=0, le=2)
    settled_cash: Money = Field(ge=0)
    daily_loss_remaining: Money = Field(ge=0)
    total_loss_remaining: Money = Field(ge=0)
    exposure_limit: Money = Field(gt=0)
    # SPY/QQQ/SPX share one cap, never separate independently funded budgets.
    index_exposure_limit: Money = Field(gt=0)
    costs_known: StrictBool
    reconciled: StrictBool
    halted: StrictBool
    plays: tuple[PlayCommitment, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def identities(self):
        for field in ("play_id", "entry_client_id", "instrument_id", "underlying"):
            values = [getattr(p, field) for p in self.plays]
            if len(values) != len(set(values)):
                raise ValueError("Duplicate portfolio " + field)
        if self.index_exposure_limit > self.exposure_limit:
            raise ValueError("Index exposure cannot exceed account exposure")
        # Lowering max_plays never invalidates an existing position or exits it.
        return self


INDEX_UNDERLYINGS = frozenset({"SPY", "QQQ", "SPX", "SPXW"})


def entry_blockers(account: PortfolioCapacity, candidate: PlayCommitment) -> tuple[str, ...]:
    """Assess one proposed reservation; caller must atomically persist or discard.

    A second choice must use the post-reservation revision, never this old view.
    This supplies capacity/funding reasons only. Native quote/metadata, original
    source, approval, calendar and protection checks remain separately mandatory.
    """
    account = PortfolioCapacity.model_validate(account.model_dump(warnings=False))
    candidate = PlayCommitment.model_validate(candidate.model_dump(warnings=False))
    if candidate.has_position or not candidate.pending_entry or candidate.uncertain:
        raise ValueError("A new entry must be an unfilled, certain reservation")
    if candidate.remaining_debit <= ZERO:
        raise ValueError("Positive entry debit required")
    with localcontext(Context(prec=192)):
        reasons = []
        if account.halted:
            reasons.append("ACCOUNT_HALTED")
        if not account.reconciled or any(p.uncertain for p in account.plays):
            reasons.append("ACCOUNT_UNCERTAIN")
        if not account.costs_known:
            reasons.append("COSTS_UNKNOWN")
        if len(account.plays) >= account.max_plays:
            reasons.append("PLAY_CAPACITY")
        for p in account.plays:
            if p.play_id == candidate.play_id or p.entry_client_id == candidate.entry_client_id:
                reasons.append("ENTRY_ALREADY_RESERVED")
            if p.instrument_id == candidate.instrument_id or p.underlying == candidate.underlying:
                reasons.append("DUPLICATE_EXPOSURE")
        required = candidate.remaining_debit + candidate.exit_reserve
        reserved = sum((p.remaining_debit + p.exit_reserve for p in account.plays), ZERO)
        invested = sum((p.invested_loss for p in account.plays), ZERO)
        if reserved + required > account.settled_cash:
            reasons.append("SETTLED_FUNDS")
        # Full-loss envelopes share the same account limits. Stops give no credit.
        committed = invested + reserved + required
        if committed > min(account.daily_loss_remaining, account.total_loss_remaining):
            reasons.append("ACCOUNT_LOSS_BUDGET")
        if committed > account.exposure_limit:
            reasons.append("ACCOUNT_EXPOSURE")
        if candidate.underlying in INDEX_UNDERLYINGS:
            index = sum(
                (
                    p.invested_loss + p.remaining_debit + p.exit_reserve
                    for p in account.plays
                    if p.underlying in INDEX_UNDERLYINGS
                ),
                ZERO,
            )
            if index + required > account.index_exposure_limit:
                reasons.append("CORRELATED_INDEX_EXPOSURE")
        return tuple(dict.fromkeys(reasons))
