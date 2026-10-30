"""Bind immutable pre-open histories to native Swing sources, never entry authority."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.mixed.carry import StockCarryPolicy, SwingCarryIntent
from app.mixed.sources import StockDailyHistory, StockSwingPolicy, StockSwingSource, validate_source
from app.mixed.stock_models import StockInstrument
from app.mixed.swing_feed import SwingHistorySnapshot
from app.options.engine import fingerprint
from app.options.models import OptionInstrument, OptionRecord, paper_market_evidence
from app.options.read_mapping import instant
from app.options.swing import (
    SwingBaseHistory,
    SwingHistory,
    SwingHourlyHistory,
    SwingLevelHistory,
    SwingMAHistory,
    SwingPolicy,
    SwingSeed,
    seed_issues,
)
from app.options.swing_batch import SwingBatchHistory, SwingBatchSeed, batch_seeds
from app.options.swing_ma_models import MA_FAMILIES
from app.options.swing_targets import SwingSeedBuildRequest, build_swing_seed
from app.robinhood.schedule import XNYSCalendar


class SwingBindingPolicy(OptionRecord):
    version: Literal["native-swing-source-binding-v1"] = "native-swing-source-binding-v1"
    runtime_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_simulation: Literal["robinhood-observed-v1"] | None = Field(default=None, exclude_if=lambda v: v is None)
    stocks: tuple[StockInstrument, ...] = Field(min_length=1, max_length=2)
    stock_policy: StockSwingPolicy | None = None
    option_policy: SwingPolicy | None = None
    candidates: tuple[OptionInstrument, ...] = Field(default=(), max_length=6)
    carry_exit_session: date | None = None
    carry_intent: SwingCarryIntent | None = Field(default=None, exclude_if=lambda v: v is None)
    stock_carry: StockCarryPolicy | None = Field(default=None, exclude_if=lambda v: v is None)
    carry_expiry_guard_seconds: int | None = Field(
        default=None, ge=0, strict=True, exclude_if=lambda v: v is None
    )


class BoundSwingSources(OptionRecord):
    version: Literal["native-swing-source-result-v1"] = "native-swing-source-result-v1"
    target_session: date
    created_at: datetime
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    history_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["PREPARED", "BLOCKED"]
    blockers: tuple[str, ...] = Field(max_length=32)
    stocks: tuple[StockSwingSource, ...] = Field(default=(), max_length=2)
    seeds: tuple[SwingSeed, ...] = Field(default=(), max_length=2)
    batches: tuple[SwingBatchSeed, ...] = Field(default=(), max_length=2)
    trading_ready: Literal[False] = False
    live_enabled: Literal[False] = False


def policy_from_settings(settings, candidates, carry_intent=None, *, observed_simulation=None):
    if observed_simulation is not None and settings.limits.mode != "PAPER":
        raise ValueError("Observed Swing histories require PAPER runtime settings")
    if carry_intent is not None:
        carry_intent = SwingCarryIntent.model_validate(carry_intent.model_dump())
        if (
            settings.stock_policy is None
            or (
                carry_intent.stock_exit_session is not None
                and (
                    settings.stock_policy.swing is None
                    or settings.execution.mixed_owner.stock_carry is None
                )
            )
            or (
                carry_intent.option_exit_session is not None
                and (
                    settings.swing_policy is None
                    or settings.swing_policy.carry is None
                    or settings.execution.swing_carry is None
                )
            )
        ):
            raise ValueError("Carry intent requires matching native asset enrollment")
    return SwingBindingPolicy(
        runtime_hash=fingerprint(settings),
        observed_simulation=observed_simulation,
        stocks=settings.stock_policy.instruments,
        stock_policy=settings.stock_policy.swing,
        option_policy=settings.swing_policy,
        candidates=candidates,
        carry_intent=carry_intent,
        stock_carry=settings.execution.mixed_owner.stock_carry
        if carry_intent is not None and carry_intent.stock_exit_session is not None
        else None,
        carry_expiry_guard_seconds=settings.execution.expiry_guard_seconds
        if carry_intent is not None and carry_intent.option_exit_session is not None
        else None,
    )


def trimmed(history, cls, count, *, version=None):
    if len(history.bars) < count:
        raise ValueError("SWING_ORIGINAL_HISTORY_TOO_SHORT")
    value = history.model_dump() | {"bars": history.bars[-count:]}
    value.pop("version", None)
    if version:
        value["version"] = version
    return cls.model_validate(value)


def bind_sources(snapshot, policy, *, created_at):
    """Use exact original bars and native validators; unknown evidence stays blocked."""
    snapshot = SwingHistorySnapshot.model_validate(snapshot.model_dump())
    policy = SwingBindingPolicy.model_validate(policy.model_dump())
    original_history_hash = fingerprint(snapshot)
    if policy.observed_simulation is not None:
        from app.mixed.observed_simulation import annotate

        snapshot = annotate(snapshot)
    created_at = instant(created_at)
    calendar = XNYSCalendar()
    symbols = tuple(i.symbol for i in policy.stocks)
    blockers, stocks, seeds, batches = [], [], [], []
    intent = policy.carry_intent
    stock_exit = intent.stock_exit_session if intent else policy.carry_exit_session
    option_exit = intent.option_exit_session if intent else policy.carry_exit_session
    if intent is not None:
        if (
            intent.target_session != snapshot.target_session
            or policy.carry_exit_session is not None
        ):
            blockers.append("SWING_CARRY_INTENT_SESSION_OR_LEGACY_CONFLICT")
        if stock_exit is not None:
            from app.mixed.carry import calendar_path

            if policy.stock_policy is None or policy.stock_carry is None:
                blockers.append("SWING_STOCK_CARRY_NOT_ENROLLED")
            else:
                try:
                    calendar_path(policy.stock_carry, calendar, snapshot.target_session, stock_exit)
                except ValueError:
                    blockers.append("SWING_STOCK_CARRY_CALENDAR_INVALID")
        if option_exit is not None and (
            policy.option_policy is None
            or policy.option_policy.carry is None
            or policy.carry_expiry_guard_seconds is None
        ):
            blockers.append("SWING_OPTION_CARRY_NOT_ENROLLED")
    if policy.stock_policy is None and policy.option_policy is None:
        blockers.append("SWING_NOT_ENROLLED")
    if (
        len(set(symbols)) != len(symbols)
        or len(snapshot.daily) != len(symbols)
        or len(snapshot.hourly) != len(symbols)
        or {h.symbol for h in snapshot.daily} != set(symbols)
        or {h.symbol for h in snapshot.hourly} != set(symbols)
    ):
        blockers.append("SWING_EXACT_HISTORY_SUBJECTS_REQUIRED")
    if len({i.instrument_id for i in policy.candidates}) != len(policy.candidates):
        blockers.append("SWING_DUPLICATE_CONTRACT_ID")
    opened = calendar.calendar.session_open(snapshot.target_session.isoformat()).to_pydatetime()
    if not snapshot.captured_at <= created_at < opened:
        blockers.append("SWING_PREOPEN_BINDING_WINDOW_REQUIRED")
    needs_hourly = (
        policy.stock_policy is not None
        and any(
            f == "SWING_DAILY_BASE" or f in MA_FAMILIES.values()
            for f in policy.stock_policy.families
        )
    ) or (
        policy.option_policy is not None
        and (
            policy.option_policy.daily_base is not None
            or policy.option_policy.ma_pullback is not None
        )
    )
    for h in (*snapshot.daily, *(snapshot.hourly if needs_hourly else ())):
        if not paper_market_evidence(h) or (h.simulation_basis is not None and policy.observed_simulation is None):
            blockers.append("SWING_HISTORY_ENTITLEMENT_REQUIRED:" + h.symbol)
        if not h.complete or not h.source_at <= h.received_at <= snapshot.captured_at:
            blockers.append("SWING_ORIGINAL_HISTORY_CLOCK_OR_COVERAGE:" + h.symbol)
    if not blockers:
        for instrument in policy.stocks:
            symbol = instrument.symbol
            daily = next(h for h in snapshot.daily if h.symbol == symbol)
            hourly = next(h for h in snapshot.hourly if h.symbol == symbol)
            if policy.stock_policy is not None:
                p = policy.stock_policy
                needs_hourly = any(
                    f == "SWING_DAILY_BASE" or f in MA_FAMILIES.values() for f in p.families
                )
                try:
                    source = StockSwingSource(
                        created_at=created_at,
                        target_session=snapshot.target_session,
                        instrument=instrument,
                        history=trimmed(daily, StockDailyHistory, p.daily_lookback),
                        hourly_history=trimmed(hourly, SwingHourlyHistory, p.hourly_lookback)
                        if needs_hourly
                        else None,
                        carry_exit_session=stock_exit,
                    )
                    stocks.append(validate_source(source, p, calendar))
                except ValueError:
                    blockers.append("SWING_NATIVE_STOCK_SOURCE_INVALID:" + symbol)
            if policy.option_policy is None:
                continue
            p = policy.option_policy
            candidates = tuple(
                i
                for i in policy.candidates
                if i.contract.underlying == symbol
                and p.minimum_dte
                <= (i.contract.expiration - snapshot.target_session).days
                <= p.maximum_dte
            )
            if (
                any(
                    i.provider != instrument.provider
                    or not i.metadata_complete
                    or not i.option_tradable
                    for i in candidates
                )
                or len(candidates) != (2 if p.family_batch else 1)
                or (p.family_batch and {i.contract.right for i in candidates} != {"CALL", "PUT"})
            ):
                blockers.append("SWING_EXACT_REVIEWED_CONTRACT_CHOICE_REQUIRED:" + symbol)
                continue
            if intent is not None and option_exit is not None:
                from app.options.swing_carry import calendar_path

                for candidate in candidates:
                    _, _, reasons = calendar_path(
                        p.carry,
                        calendar,
                        snapshot.target_session,
                        option_exit,
                        candidate.contract,
                        policy.carry_expiry_guard_seconds,
                    )
                    blockers.extend(reasons)
                if blockers:
                    continue
            hp = p.daily_base or p.ma_pullback
            try:
                hour = trimmed(hourly, SwingHourlyHistory, hp.hourly_lookback) if hp else None
                if p.family_batch:
                    batch = SwingBatchSeed(
                        created_at=created_at,
                        target_session=snapshot.target_session,
                        history=trimmed(daily, SwingBatchHistory, p.daily_lookback),
                        hourly_history=hour,
                        instruments=tuple(sorted(candidates, key=lambda i: i.contract.right)),
                        carry_exit_session=option_exit,
                    )
                    # Enumerate and validate every native variant before retaining
                    # the original root. A model never selects which source to omit.
                    batch_seeds(batch, p, calendar, symbols)
                    batches.append(batch)
                    continue
                if (p.ma_pullback and len(p.ma_pullback.periods) != 1) or (
                    p.higher_levels and len(p.higher_levels.keys) != 1
                ):
                    blockers.append("SWING_EXPLICIT_SINGLE_VARIANT_REQUIRED:" + symbol)
                    continue
                cls, version = (
                    (SwingLevelHistory, "swing-level-daily-v1")
                    if p.higher_levels
                    else (SwingMAHistory, "swing-ma-daily-v1")
                    if p.ma_pullback
                    else (SwingBaseHistory, "swing-base-daily-v1")
                    if p.daily_base
                    else (SwingHistory, None)
                )
                values = {
                    "created_at": created_at,
                    "target_session": snapshot.target_session,
                    "history": trimmed(daily, cls, p.daily_lookback, version=version),
                    "hourly_history": hour,
                    "instrument": candidates[0],
                    "ma_period": p.ma_pullback.periods[0] if p.ma_pullback else None,
                    "level_key": p.higher_levels.keys[0] if p.higher_levels else None,
                    "carry_exit_session": option_exit,
                }
                if p.target_derivation:
                    seed = build_swing_seed(
                        SwingSeedBuildRequest(policy=p, symbols=symbols, **values)
                    )
                else:
                    seed = SwingSeed(**values)
                    if seed_issues(seed, p, calendar, symbols):
                        raise ValueError("Invalid native original seed")
                seeds.append(seed)
            except ValueError:
                blockers.append("SWING_NATIVE_OPTION_SEED_INVALID:" + symbol)
    return BoundSwingSources(
        target_session=snapshot.target_session,
        created_at=created_at,
        policy_hash=fingerprint(policy),
        history_hash=original_history_hash,
        status="BLOCKED" if blockers else "PREPARED",
        blockers=tuple(sorted(set(blockers))),
        stocks=tuple(stocks) if not blockers else (),
        seeds=tuple(seeds) if not blockers else (),
        batches=tuple(batches) if not blockers else (),
    )
