"""Candidate-specific option admission against the complete shared native history.

Uses the existing quote/calendar/contract/fee governor. Original strategy approval,
atomic reservation and fresh dispatch are still responsibilities of the owner.
"""

from decimal import Context, localcontext
from typing import Literal

from app.mixed.accounting import reconstruct
from app.mixed.governor import _account
from app.mixed.models import Digest
from app.mixed.portfolio_accounting import (
    PortfolioHistory,
    candidate_blockers,
    parse_history,
    remaining_budget,
)
from app.options.engine import fingerprint
from app.options.governor import admit_option
from app.options.models import Name, OptionAdmission, OptionProposal


class PortfolioOptionAdmission(OptionAdmission):
    policy_version: Literal["mixed-portfolio-option-admission-v2"] = (
        "mixed-portfolio-option-admission-v2"
    )
    history_hash: Digest
    proposal_hash: Digest
    play_id: Name | None


def admit_portfolio_option(
    proposal,
    quote,
    underlying,
    history,
    session,
    *,
    now,
    reconciled=False,
    entry_halted=False,
    play_id=None,
):
    history = parse_history(history)
    if not isinstance(history, PortfolioHistory):
        raise ValueError("Versioned portfolio history required")  # noqa: TRY004 -- enrollment version
    proposal = OptionProposal.model_validate(proposal.model_dump(warnings=False))
    if (proposal.action == "CLOSE") != (play_id is not None):
        raise ValueError("Only a portfolio close requires exact play identity")
    with localcontext(Context(prec=192)):
        result = reconstruct(history)
        account = _account(history, result, reconciled, entry_halted, play_id=play_id)
        if proposal.action == "OPEN_LONG":
            contract = proposal.contract
            budget = remaining_budget(history, result, contract.underlying)
            account = account.model_copy(
                update={
                    "daily_loss_available": budget,
                    "total_loss_available": budget,
                    "entry_blockers": candidate_blockers(
                        history, result, contract.underlying, contract.contract_id
                    ),
                }
            )
        # Match the native owner's worst-case one close order per contract reserve.
        limits = history.policy.options
        effective = type(limits).model_validate(
            {
                **limits.model_dump(),
                "exit_fee_per_order": "0",
                "exit_fee_per_contract": limits.exit_fee_per_contract + limits.exit_fee_per_order,
            }
        )
        admitted = admit_option(proposal, quote, underlying, account, effective, session, now=now)
        return PortfolioOptionAdmission(
            **admitted.model_dump(exclude={"policy_version"}),
            history_hash=fingerprint(history),
            proposal_hash=fingerprint(proposal),
            play_id=play_id,
        )
