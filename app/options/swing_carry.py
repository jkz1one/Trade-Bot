"""Offline Swing carry preflight. No enrollment, orders, holding extension or P&L."""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.options.carry_models import CarrySession, SwingCarryPolicy
from app.options.degen import DegenHistory, DegenPolicy, scan_degen
from app.options.engine import fingerprint
from app.options.governor import admit_option
from app.options.lifecycle import CALENDAR_SOURCE, OptionExecutionPolicy
from app.options.models import (
    Name,
    OptionAccount,
    OptionAdmission,
    OptionLimits,
    OptionProposal,
    OptionQuote,
    OptionRecord,
    SessionWindow,
    UnderlyingQuote,
)
from app.options.selection import ContractReadPlan, ContractSelectionPolicy
from app.options.swing import (
    SwingInput,
    SwingPolicy,
    SwingScan,
    SwingTerminal,
    plan_swing_reads,
    scan_swing,
)
from app.options.swing_lifecycle import apply_terminal, quote_terminal
from app.robinhood.schedule import XNYSCalendar

MAX_BYTES = 2 * 1024 * 1024


class SwingCarryRequest(OptionRecord):
    version: Literal["swing-carry-request-v1"] = "swing-carry-request-v1"
    at: datetime
    exit_session: date
    carry: SwingCarryPolicy
    swing: SwingPolicy
    structure: DegenPolicy
    selection: ContractSelectionPolicy
    execution: OptionExecutionPolicy
    limits: OptionLimits
    item: SwingInput
    history: DegenHistory
    quote: OptionQuote | None
    underlying: UnderlyingQuote | None
    account: OptionAccount
    retained_terminal: SwingTerminal | None = None


class SwingCarryReview(OptionRecord):
    version: Literal["swing-carry-review-v1"] = "swing-carry-review-v1"
    authority: Literal[False] = False
    evidence_status: Literal["READY", "BLOCKED"]
    execution_blockers: tuple[Literal["SWING_OVERNIGHT_EXECUTION_NOT_ENROLLED"], ...] = (
        "SWING_OVERNIGHT_EXECUTION_NOT_ENROLLED",
    )
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    seed_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    account_id: Name
    population_id: Name
    reasons: tuple[Name, ...]
    sessions: tuple[CarrySession, ...] = Field(max_length=21)
    proposed_exit_at: datetime | None
    scan: SwingScan | None
    read_plan: ContractReadPlan | None
    admission: OptionAdmission | None


def _calendar_path(r, calendar):
    """Bound the date span before calling the installed exchange calendar."""
    start = r.item.seed.target_session
    days = (r.exit_session - start).days
    if not 0 < days <= r.carry.maximum_calendar_days:
        return (), None, ("SWING_CARRY_CALENDAR_SPAN",)
    cal = calendar.calendar
    if not cal.is_session(start.isoformat()) or not cal.is_session(r.exit_session.isoformat()):
        return (), None, ("SWING_CARRY_EXACT_SESSIONS_REQUIRED",)
    labels = cal.sessions_in_range(start.isoformat(), r.exit_session.isoformat())
    if len(labels) - 1 > r.carry.maximum_carry_sessions:
        return (), None, ("SWING_CARRY_SESSION_LIMIT",)
    path = tuple(
        CarrySession(
            session=s.date(),
            opens_at=cal.session_open(s).to_pydatetime(),
            closes_at=cal.session_close(s).to_pydatetime(),
        )
        for s in labels
    )
    deadline = path[-1].closes_at - timedelta(minutes=r.carry.exit_before_close_minutes)
    reasons = []
    if deadline <= path[-1].opens_at:
        reasons.append("SWING_CARRY_EXIT_WINDOW_EMPTY")
    contract = r.item.seed.instrument.contract
    if not cal.is_session(contract.expiration.isoformat()):
        reasons.append("SWING_CARRY_EXPIRY_SESSION_REQUIRED")
    else:
        last_exit = contract.expiration.isoformat()
        for _ in range(r.carry.expiry_session_buffer):
            last_exit = cal.previous_session(last_exit)
        if r.exit_session > last_exit.date():
            reasons.append("SWING_CARRY_EXPIRY_BUFFER")
        # Use the earlier explicit contract instant, not an assumed 16:00 expiry.
        if deadline >= contract.last_trading_at - timedelta(
            seconds=r.execution.expiry_guard_seconds
        ):
            reasons.append("SWING_CARRY_CONTRACT_CUTOFF")
    if r.item.catalyst.valid_through < deadline:
        reasons.append("SWING_CARRY_CATALYST_HORIZON")
    return path, deadline, tuple(reasons)


def review_swing_carry(request):
    """Recompute current setup/admission and future calendar coverage from supplied evidence.

    No claim is made about journal ownership, unobserved prices or future liquidity.
    A READY result still cannot extend the current SESSION_CLOSE native policy.
    """
    r = SwingCarryRequest.model_validate(request.model_dump(warnings=False))
    with localcontext(Context(prec=192)):
        return _review(r)


def _review(r):
    reasons = []
    path, deadline, scan, plan, admission = (), None, None, None, None
    if r.swing.unfilled_lifecycle != "observed-lifecycle-v3":
        reasons.append("SWING_CARRY_ORIGINAL_TARGET_LIFECYCLE_REQUIRED")
    if r.limits.session_source != CALENDAR_SOURCE or not set(r.structure.symbols) <= set(
        r.limits.allowed_underlyings
    ):
        reasons.append("SWING_CARRY_OWNER_POLICY_BINDING")
    if r.quote is not None and r.quote.instrument != r.item.seed.instrument:
        reasons.append("SWING_CONTRACT_LOCK_CHANGED")
    terminal = r.retained_terminal
    if terminal is not None:
        if terminal.seed_hash != fingerprint(r.item.seed) or terminal.observed_at > r.at:
            reasons.append("SWING_CARRY_TERMINAL_BINDING")
        reasons.append("SWING_SEED_TERMINAL")
    calendar = XNYSCalendar()
    try:
        path, deadline, calendar_reasons = _calendar_path(r, calendar)
        reasons.extend(calendar_reasons)
        window = calendar.current_window(r.at)
        intraday = scan_degen(r.history, r.structure, window, now=r.at)
        scan = scan_swing(
            r.item,
            r.swing,
            intraday,
            r.history,
            calendar,
            r.structure.symbols,
            now=r.at,
            receive_lag=r.limits.max_receive_lag_seconds,
        )
        if r.underlying is not None:
            observed = quote_terminal(r.item.seed, r.swing, r.limits, calendar, r.underlying, r.at)
            scan = apply_terminal(scan, scan.terminal or observed)
        plan = plan_swing_reads(scan, r.item, r.selection, r.limits, now=r.at)
        reasons.extend(scan.issues)
        reasons.extend(scan.observations[0].reasons)
        reasons.extend(plan.issues)
        for excluded in plan.exclusions.values():
            reasons.extend(excluded)
        # Same current break/chase requirement as native dispatch; never extrapolate it.
        reference = scan.observations[0].reference
        u, call = r.underlying, r.item.seed.instrument.contract.right == "CALL"
        if (
            u is not None
            and reference is not None
            and (
                (u.bid <= reference if call else u.ask >= reference)
                or abs((u.ask if call else u.bid) / reference - 1) > r.swing.maximum_chase_fraction
            )
        ):
            reasons.append("SWING_CURRENT_BREAK_OR_CHASE_REJECTED")
        if scan.observations[0].invalidation is not None:
            contract = r.item.seed.instrument.contract
            session = None
            if window is not None:
                end = min(window.closes_at, contract.last_trading_at)
                cutoff = min(
                    window.closes_at - timedelta(minutes=r.execution.entry_cutoff_minutes),
                    end - timedelta(seconds=r.execution.expiry_guard_seconds),
                )
                if cutoff > window.opens_at:
                    session = SessionWindow(
                        source=CALENDAR_SOURCE,
                        underlying=contract.underlying,
                        opens_at=window.opens_at,
                        entry_cutoff_at=cutoff,
                        closes_at=end,
                    )
            # Reserve one exit-order fee per contract, exactly as native entry sizing.
            effective = OptionLimits.model_validate(
                {
                    **r.limits.model_dump(),
                    "exit_fee_per_order": Decimal(0),
                    "exit_fee_per_contract": r.limits.exit_fee_per_contract
                    + r.limits.exit_fee_per_order,
                }
            )
            admission = admit_option(
                OptionProposal(
                    action="OPEN_LONG",
                    contract=contract,
                    underlying_invalidation=scan.observations[0].invalidation,
                    thesis="Swing carry research preflight; no overnight execution authority",
                ),
                r.quote,
                r.underlying,
                r.account,
                effective,
                session,
                now=r.at,
            )
            reasons.extend(admission.reasons)
    except (ValueError, OverflowError) as exc:
        # Out-of-range calendar evidence blocks, rather than guessing weekdays.
        from exchange_calendars.errors import DateOutOfBounds, RequestedSessionOutOfBounds

        if not isinstance(exc, (DateOutOfBounds, RequestedSessionOutOfBounds, OverflowError)):
            raise
        reasons.append("SWING_CARRY_CALENDAR_UNAVAILABLE")
    reasons = tuple(dict.fromkeys(reasons))
    return SwingCarryReview(
        evidence_status="BLOCKED" if reasons else "READY",
        reasons=reasons,
        request_hash=fingerprint(r),
        seed_hash=fingerprint(r.item.seed),
        policy_hash=fingerprint(
            {
                "carry": r.carry,
                "swing": r.swing,
                "structure": r.structure,
                "selection": r.selection,
                "execution": r.execution,
                "limits": r.limits,
            }
        ),
        account_id=r.limits.account_id,
        population_id=r.limits.population_id,
        sessions=path,
        proposed_exit_at=deadline,
        scan=scan,
        read_plan=plan,
        admission=admission,
    )


def export_swing_carry(request):
    r = SwingCarryRequest.model_validate(request.model_dump(warnings=False))
    return {
        "version": "swing-carry-export-v1",
        "request": r.model_dump(mode="json"),
        "review": review_swing_carry(r).model_dump(mode="json"),
    }


def verify_swing_carry_export(value, *, expected_request_hash):
    """Requires an independently retained input hash; never restores native state."""
    if not isinstance(value, dict) or set(value) != {"version", "request", "review"}:
        raise ValueError("Exact Swing carry export fields required")
    if len(json.dumps(value).encode()) > MAX_BYTES:
        raise ValueError("Swing carry export exceeds capacity")
    request = SwingCarryRequest.model_validate(value["request"])
    if fingerprint(request) != expected_request_hash:
        raise ValueError("Swing carry request identity changed")
    expected = export_swing_carry(request)
    if fingerprint(value) != fingerprint(expected):
        raise ValueError("Swing carry review does not reproduce")
    return expected["review"]


def _load(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Swing carry input exceeds capacity")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("review")
    create.add_argument("request", type=Path)
    create.add_argument("output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("export", type=Path)
    verify.add_argument("--request-hash", required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            report = verify_swing_carry_export(
                _load(args.export), expected_request_hash=args.request_hash
            )
        else:
            if not args.output.is_absolute():
                raise ValueError("Absolute create-only output path required")
            value = export_swing_carry(SwingCarryRequest.model_validate(_load(args.request)))
            encoded = (json.dumps(value, indent=2) + "\n").encode()
            if len(encoded) > MAX_BYTES:
                raise ValueError("Swing carry export exceeds capacity")
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            report = value["review"]
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "evidence_status",
                        "authority",
                        "execution_blockers",
                        "request_hash",
                        "reasons",
                    )
                }
            )
        )
        return 0
    except (ValueError, OSError) as exc:
        print(f"Swing carry preflight failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
