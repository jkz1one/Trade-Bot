"""Completed source evidence for long shares; never synthetic option contracts."""

from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from app.mixed.carry import StockCatalyst, derive_terms
from app.mixed.models import StockProposal
from app.mixed.stock_models import StockInstrument, StockQuote
from app.options.degen import DegenHistory, DegenPolicy, Family, _metric, scan_degen
from app.options.engine import exact, fingerprint
from app.options.governor import _fresh
from app.options.models import Money, Name, OptionRecord
from app.options.swing import SwingHourlyHistory, SwingMAHistory
from app.options.swing_base_models import SwingFamily
from app.options.swing_level_models import LEVEL_FAMILIES
from app.options.swing_ma_models import MA_FAMILIES


class StockDailyHistory(SwingMAHistory):
    version: Literal["stock-swing-daily-v1"] = "stock-swing-daily-v1"


class StockSwingPolicy(OptionRecord):
    version: Literal["stock-original-swing-v1"] = "stock-original-swing-v1"
    families: tuple[SwingFamily, ...] = Field(min_length=1, max_length=10)
    history_source: Name
    daily_lookback: int = Field(strict=True, ge=56, le=260)
    hourly_source: Name
    hourly_lookback: int = Field(strict=True, ge=54, le=260)
    catalyst_source: Name
    catalyst_max_age_seconds: int = Field(strict=True, gt=0, le=60)
    maximum_chase_fraction: Money = Field(gt=0, le=Decimal(".1"))
    stop_buffer_fraction: Money = Field(gt=0, le=Decimal(".01"))

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.families)) != len(self.families):
            raise ValueError("Unique frozen stock Swing families required")
        return self


class StockSelectionPolicy(OptionRecord):
    version: Literal["native-stock-selection-v1"] = "native-stock-selection-v1"
    paid_selection: Literal["mixed-paid-entry-v1"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    instruments: tuple[StockInstrument, ...] = Field(min_length=1, max_length=2)
    family_priority: tuple[Literal["DEGEN", "SWING", "SCOPE"], ...] = Field(
        min_length=1, max_length=3
    )
    asset_priority: tuple[Literal["STOCK", "OPTION"], Literal["STOCK", "OPTION"]]
    swing: StockSwingPolicy | None = None

    @model_validator(mode="after")
    def unique(self):
        if (
            len({i.symbol for i in self.instruments}) != len(self.instruments)
            or len({i.instrument_id for i in self.instruments}) != len(self.instruments)
            or len(set(self.family_priority)) != len(self.family_priority)
            or "DEGEN" not in self.family_priority
            or set(self.asset_priority) != {"STOCK", "OPTION"}
            or (self.swing is not None and "SWING" not in self.family_priority)
        ):
            raise ValueError("Exact stock universe and unique complete priorities required")
        return self


class StockSwingSource(OptionRecord):
    version: Literal["stock-original-swing-source-v1"] = "stock-original-swing-source-v1"
    created_at: datetime
    target_session: date
    instrument: StockInstrument
    history: StockDailyHistory
    hourly_history: SwingHourlyHistory | None = None
    carry_exit_session: date | None = None


class StockCycleInput(OptionRecord):
    quote: StockQuote
    swing: StockSwingSource | None = None
    catalyst: StockCatalyst | None = None


class StockSourceCandidate(OptionRecord):
    candidate_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    setup_family: Family | SwingFamily
    reference: Money = Field(gt=0)
    targets: tuple[Money, Money, Money]
    proposal: StockProposal


class _Seed:
    """Data-only source view for existing arithmetic; no option instrument is fabricated."""

    def __init__(self, source, family):
        self.history, self.hourly_history = source.history, source.hourly_history
        self.ma_period = next((p for p, f in MA_FAMILIES.items() if f == family), None)
        self.level_key = next((p for p, f in LEVEL_FAMILIES.items() if f == family), None)


def validate_source(source, policy, calendar):
    source = StockSwingSource.model_validate(source.model_dump(warnings=False))
    policy = StockSwingPolicy.model_validate(policy.model_dump(warnings=False))
    h, cal = source.history, calendar.calendar
    target = source.target_session.isoformat()
    if not cal.is_session(target):
        raise ValueError("STOCK_SOURCE_TARGET_SESSION_REQUIRED")
    previous = cal.previous_session(target)
    close = cal.session_close(previous).to_pydatetime()
    opened = cal.session_open(target).to_pydatetime()
    if (
        h.symbol != source.instrument.symbol
        or h.source != policy.history_source
        or not h.complete
        or h.entitlement != "REALTIME"
        or len(h.bars) != policy.daily_lookback
        or not close <= h.source_at <= h.received_at <= source.created_at < opened
    ):
        raise ValueError("STOCK_ORIGINAL_DAILY_SOURCE_REQUIRED")
    expected = previous
    for b in reversed(h.bars):
        if (
            b.begins_at != cal.session_open(expected).to_pydatetime()
            or b.closes_at != cal.session_close(expected).to_pydatetime()
            or b.closes_at > h.source_at
            or b.interpolated
            or b.volume <= 0
        ):
            raise ValueError("STOCK_DAILY_SOURCE_GAPPED_OR_UNFINISHED")
        expected = cal.previous_session(expected)
    hourly_needed = any(
        f == "SWING_DAILY_BASE" or f in MA_FAMILIES.values() for f in policy.families
    )
    hourly = source.hourly_history
    if hourly_needed != (hourly is not None):
        raise ValueError("STOCK_EXACT_HOURLY_SOURCE_COVERAGE_REQUIRED")
    if hourly is not None:
        if (
            hourly.symbol != h.symbol
            or hourly.source != policy.hourly_source
            or not hourly.complete
            or hourly.entitlement != "REALTIME"
            or len(hourly.bars) != policy.hourly_lookback
            or not close <= hourly.source_at <= hourly.received_at <= source.created_at
        ):
            raise ValueError("STOCK_ORIGINAL_HOURLY_SOURCE_REQUIRED")
        expected, end = previous, close
        for b in reversed(hourly.bars):
            start = cal.session_open(expected).to_pydatetime()
            begins = start + timedelta(hours=int((end - start).total_seconds() - 1) // 3600)
            if (
                b.begins_at != begins
                or b.closes_at != end
                or b.closes_at > hourly.source_at
                or b.interpolated
                or b.volume <= 0
            ):
                raise ValueError("STOCK_HOURLY_SOURCE_GAPPED_OR_UNFINISHED")
            end = begins
            if begins == start:
                expected = cal.previous_session(expected)
                end = cal.session_close(expected).to_pydatetime()
    return source


@exact
def geometry(source, family, policy):
    from app.options.swing_base import evaluate_base
    from app.options.swing_levels import evaluate_level
    from app.options.swing_ma import evaluate_ma

    seed = _Seed(source, family)
    if family in LEVEL_FAMILIES.values():
        result = evaluate_level(seed, bullish=True)
    elif family in MA_FAMILIES.values():
        result = evaluate_ma(seed, bullish=True)
    elif family == "SWING_DAILY_BASE":
        result = evaluate_base(seed, bullish=True)
    elif family == "SWING_DAILY_BREAKOUT":
        b = source.history.bars[-1]
        reference, stop = b.high, _metric(b.low * (1 - policy.stop_buffer_fraction), ROUND_CEILING)
        reasons = (
            ("SWING_DAILY_TREND_REQUIRED",)
            if any(b.close <= a.close for a, b in pairwise(source.history.bars))
            else ()
        )
        return reference, stop, reasons
    else:
        raise ValueError("STOCK_FAMILY_NOT_SUPPORTED")
    return result.reference, result.invalidation, result.reasons


@exact
def candidate(
    family, reference, stop, source_hash, instrument, source_at, valid_until, exit_at, carry=None
):
    targets = tuple(reference + (reference - stop) * n for n in (1, 2, 3))
    proposal = StockProposal(
        action="OPEN_LONG",
        instrument=instrument,
        family="SWING" if family.startswith("SWING_") else "DEGEN",
        source_hash=source_hash,
        source_at=source_at,
        valid_until=valid_until,
        exit_at=exit_at,
        carry=carry,
        original_invalidation=stop,
        original_target=targets[0],
        thesis=f"{family}: original completed source, fixed risk ladder and native protection",
    )
    fields = {
        "setup_family": family,
        "reference": reference,
        "targets": targets,
        "proposal": proposal,
    }
    return StockSourceCandidate(candidate_id=fingerprint(fields), **fields)


@exact
def candidates(item, history, structure, policy, execution, calendar, *, now, swing_unavailable=False):
    """Recompute source signals; account admission and native attempt remain separate."""
    from app.options.lifecycle import OptionExecutionPolicy

    execution = OptionExecutionPolicy.model_validate(execution.model_dump(warnings=False))
    if execution.mixed_owner is None:
        raise ValueError("Stock sources require a native mixed owner")
    item = StockCycleInput.model_validate(item.model_dump(warnings=False))
    history = DegenHistory.model_validate(history.model_dump(warnings=False))
    structure = DegenPolicy.model_validate(structure.model_dump(warnings=False))
    policy = StockSelectionPolicy.model_validate(policy.model_dump(warnings=False))
    q, w = item.quote, calendar.current_window(now)
    instrument = next((i for i in policy.instruments if i.symbol == history.symbol), None)
    if q.instrument != instrument or w is None:
        raise ValueError("STOCK_SOURCE_INSTRUMENT_OR_SESSION_MISMATCH")
    scan = scan_degen(history, structure, w, now=now)
    if scan.issues:
        return (), {"DEGEN": scan.issues}, {}
    limits = execution.mixed_owner.stocks
    quote_bad = (
        q.source != limits.quote_source
        or not q.complete
        or q.entitlement != "REALTIME"
        or not _fresh(
            q.source_at,
            q.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    )
    exit_at = w.closes_at - timedelta(minutes=execution.exit_cutoff_minutes)
    valid_until = min(
        w.closes_at - timedelta(minutes=execution.entry_cutoff_minutes),
        history.source_at + timedelta(seconds=structure.max_bar_age_seconds),
    )
    found, rejected, terminals = [], {}, {}
    if quote_bad:
        rejected["quote"] = ("STOCK_SOURCE_FRESH_QUOTE_REQUIRED",)
    for setup in scan.observations:
        if quote_bad or setup.status != "CONFIRMED" or setup.right != "CALL":
            continue
        # The original completed signal close anchors the stock risk ladder. A later
        # quote cannot move its objectives; the source reference remains in the scan hash.
        c = candidate(
            setup.family,
            scan.last_close,
            setup.invalidation,
            fingerprint({"history": history, "structure": structure, "setup": setup}),
            instrument,
            history.source_at,
            valid_until,
            exit_at,
        )
        if q.bid <= c.proposal.original_invalidation or q.ask >= c.targets[0]:
            rejected[setup.family] = ("STOCK_ORIGINAL_GEOMETRY_CONSUMED",)
        else:
            found.append(c)
    if swing_unavailable:
        if item.swing is not None or item.catalyst is not None:
            raise ValueError("Unavailable Swing cannot carry sources")
        rejected["SWING"] = ("SWING_INPUT_UNAVAILABLE",)
        return tuple(found), rejected, terminals
    if policy.swing is None:
        if item.swing is not None or item.catalyst is not None:
            raise ValueError("STOCK_SWING_NOT_ENROLLED")
        return tuple(found), rejected, terminals
    if item.swing is None or item.catalyst is None:
        raise ValueError("STOCK_COMPLETE_SWING_SOURCE_REQUIRED")
    p, s, cat = policy.swing, validate_source(item.swing, policy.swing, calendar), item.catalyst
    if s.instrument != instrument or s.target_session.isoformat() != w.session_date:
        raise ValueError("STOCK_ORIGINAL_SWING_SESSION_OR_IDENTITY_REQUIRED")
    carry = None
    source_hash = fingerprint(s)
    if s.carry_exit_session is not None:
        cp = execution.mixed_owner.stock_carry
        if cp is None:
            raise ValueError("STOCK_CARRY_NOT_ENROLLED")
        from app.mixed.carry import calendar_path

        _, exit_at = calendar_path(cp, calendar, s.target_session, s.carry_exit_session)
        if cat.valid_through >= exit_at:
            carry = derive_terms(
                cp,
                calendar,
                source_hash=source_hash,
                catalyst=cat,
                now=now,
                exit_session=s.carry_exit_session,
            )
    catalyst_bad = (
        cat.symbol != instrument.symbol
        or cat.source != p.catalyst_source
        or cat.status != "CLEAR"
        or not cat.complete
        or cat.entitlement != "REALTIME"
        or not _fresh(
            cat.source_at,
            cat.received_at,
            now,
            p.catalyst_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
        or cat.valid_through < exit_at
    )
    completed = [
        b for b in history.bars if b.ends_at <= min(now, history.source_at, history.received_at)
    ]
    for family in p.families:
        reference, stop, reasons = geometry(s, family, p)
        if reasons:
            rejected[family] = reasons
            continue
        target = reference + (reference - stop)
        terminal = next(
            (
                "INVALIDATED" if b.low <= stop else "TARGET_CONSUMED"
                for b in completed
                if b.low <= stop or b.high >= target
            ),
            None,
        )
        if terminal is None and not quote_bad and (q.bid <= stop or q.bid >= target):
            terminal = "INVALIDATED" if q.bid <= stop else "TARGET_CONSUMED"
        if terminal:
            terminals[family] = terminal
            rejected[family] = ("STOCK_SEED_" + terminal,)
        elif catalyst_bad or quote_bad:
            rejected[family] = ("STOCK_ORIGINAL_CATALYST_OR_QUOTE_REQUIRED",)
        elif (
            len(completed) < 6
            or any(b.close <= reference for b in completed[-2:])
            or q.bid <= reference
            or abs(q.ask / reference - 1) > p.maximum_chase_fraction
            or abs(scan.last_close / reference - 1) > p.maximum_chase_fraction
        ):
            rejected[family] = ("STOCK_CURRENT_BREAK_OR_CHASE_REQUIRED",)
        else:
            found.append(
                candidate(
                    family,
                    reference,
                    stop,
                    source_hash,
                    instrument,
                    s.created_at,
                    valid_until,
                    exit_at,
                    carry,
                )
            )
    return tuple(found), rejected, terminals
