"""Original long-share carry horizons; no option expiry or synthetic contract."""

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.options.carry_models import CarrySession
from app.options.governor import _fresh
from app.options.models import Evidence, Name, OptionRecord, Symbol


class StockCarryPolicy(OptionRecord):
    version: Literal["mixed-stock-carry-v1"] = "mixed-stock-carry-v1"
    maximum_carry_sessions: int = Field(strict=True, ge=1, le=20)
    maximum_calendar_days: int = Field(strict=True, ge=1, le=60)
    exit_before_close_minutes: int = Field(strict=True, ge=1, le=120)
    catalyst_source: Name
    catalyst_max_age_seconds: int = Field(strict=True, ge=1, le=60)


class StockCatalyst(Evidence):
    symbol: Symbol
    status: Literal["CLEAR", "BLOCKED", "UNKNOWN"]
    valid_through: datetime


class StockCarryTerms(OptionRecord):
    version: Literal["original-stock-carry-v1"] = "original-stock-carry-v1"
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    sessions: tuple[CarrySession, ...] = Field(min_length=2, max_length=21)
    exit_at: datetime
    catalyst: StockCatalyst

    @model_validator(mode="after")
    def ordered(self):
        if (
            any(s.opens_at >= s.closes_at for s in self.sessions)
            or any(a.closes_at >= b.opens_at for a, b in zip(self.sessions, self.sessions[1:]))
            or not self.sessions[-1].opens_at < self.exit_at < self.sessions[-1].closes_at
            or self.catalyst.valid_through < self.exit_at
        ):
            raise ValueError("Original ordered stock carry horizon and catalyst coverage required")
        return self


def calendar_path(policy, calendar, start, end):
    if not 0 < (end - start).days <= policy.maximum_calendar_days:
        raise ValueError("STOCK_CARRY_CALENDAR_SPAN")
    cal = calendar.calendar
    if not cal.is_session(start.isoformat()) or not cal.is_session(end.isoformat()):
        raise ValueError("STOCK_CARRY_EXACT_SESSIONS_REQUIRED")
    labels = cal.sessions_in_range(start.isoformat(), end.isoformat())
    if len(labels) - 1 > policy.maximum_carry_sessions:
        raise ValueError("STOCK_CARRY_SESSION_LIMIT")
    path = tuple(
        CarrySession(
            session=s.date(),
            opens_at=cal.session_open(s).to_pydatetime(),
            closes_at=cal.session_close(s).to_pydatetime(),
        )
        for s in labels
    )
    exit_at = path[-1].closes_at - timedelta(minutes=policy.exit_before_close_minutes)
    if exit_at <= path[-1].opens_at:
        raise ValueError("STOCK_CARRY_EXIT_WINDOW_EMPTY")
    return path, exit_at


def derive_terms(policy, calendar, *, source_hash, catalyst, now, exit_session: date):
    """Derive original calendar evidence, not entry approval or permission to extend."""
    from app.options.engine import clock, fingerprint

    now = clock(now)
    policy = StockCarryPolicy.model_validate(policy.model_dump(warnings=False))
    path, exit_at = calendar_path(
        policy, calendar, now.astimezone(ZoneInfo("America/New_York")).date(), exit_session
    )
    if not path[0].opens_at <= now < path[0].closes_at:
        raise ValueError("STOCK_CARRY_ENTRY_SESSION_REQUIRED")
    return StockCarryTerms(
        source_hash=source_hash,
        policy_hash=fingerprint(policy),
        sessions=path,
        exit_at=exit_at,
        catalyst=catalyst,
    )


def verify_terms(policy, calendar, terms, *, source_hash, symbol, exit_at):
    from app.options.engine import fingerprint

    if policy is None:
        raise ValueError("STOCK_CARRY_NOT_ENROLLED")
    path, deadline = calendar_path(
        policy, calendar, terms.sessions[0].session, terms.sessions[-1].session
    )
    if (
        terms.policy_hash != fingerprint(policy)
        or terms.source_hash != source_hash
        or terms.sessions != path
        or terms.exit_at != deadline
        or exit_at != deadline
        or terms.catalyst.symbol != symbol
        or terms.catalyst.source != policy.catalyst_source
        or terms.catalyst.status != "CLEAR"
        or not terms.catalyst.complete
        or terms.catalyst.entitlement != "REALTIME"
        or terms.catalyst.valid_through < deadline
    ):
        raise ValueError("STOCK_CARRY_ORIGINAL_TERMS_REQUIRED")


def review_entry(policy, calendar, proposal, now, receive_lag):
    terms = proposal.carry
    verify_terms(
        policy,
        calendar,
        terms,
        source_hash=proposal.source_hash,
        symbol=proposal.instrument.symbol,
        exit_at=proposal.exit_at,
    )
    if (
        proposal.family != "SWING"
        or not terms.sessions[0].opens_at <= now < terms.sessions[0].closes_at
        or not _fresh(
            terms.catalyst.source_at,
            terms.catalyst.received_at,
            now,
            policy.catalyst_max_age_seconds,
            receive_lag,
        )
    ):
        raise ValueError("STOCK_CARRY_ORIGINAL_ENTRY_OR_CATALYST_EXPIRED")
