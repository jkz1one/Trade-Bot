"""Local earnings/IV evidence diagnostics; no pricing forecast or execution authority."""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Literal

from pydantic import Field

from app.events.assessment import worst
from app.options.engine import fingerprint
from app.options.models import OptionRecord


class OptionVolatilityPolicy(OptionRecord):
    version: Literal["earnings-iv-research-v1"] = "earnings-iv-research-v1"
    label: Literal["PROVISIONAL_RESEARCH_NOT_VALIDATED"] = "PROVISIONAL_RESEARCH_NOT_VALIDATED"
    mode: Literal["OBSERVATION_ONLY"] = "OBSERVATION_ONLY"
    before_seconds: int = Field(default=259200, ge=0, le=604800)
    after_seconds: int = Field(default=86400, gt=0, le=604800)
    quote_max_age_seconds: int = Field(default=10, gt=0, le=300)
    max_receive_lag_seconds: int = Field(default=2, ge=0, le=60)
    max_sync_seconds: int = Field(default=2, ge=0, le=60)
    max_valid_seconds: int = Field(default=10, gt=0, le=60)
    max_events: int = Field(default=256, gt=0, le=512)


@dataclass(frozen=True)
class OptionVolatilityView:
    risk: object
    policy: OptionVolatilityPolicy
    policy_hash: str
    events: object


def prepare_option_volatility(risk, policy=None):
    """Background-only indexing; keep original snapshot and base policy identity."""
    policy = OptionVolatilityPolicy.model_validate_json(
        (policy or OptionVolatilityPolicy()).model_dump_json()
    )
    indexed = {}
    for symbol, (_, items) in risk.events.items():
        selected = []
        for item in items:
            e = item.event
            if e.scope == "SYMBOL" and (
                e.category == "company.earnings" or e.category.startswith("company.earnings.")
            ):
                selected.append(
                    (
                        e.starts_at - timedelta(seconds=policy.before_seconds),
                        e.ends_at + timedelta(seconds=policy.after_seconds),
                        item,
                    )
                )
        selected.sort(key=lambda row: row[0])
        indexed[symbol] = (tuple(row[0] for row in selected), tuple(selected))
    return OptionVolatilityView(risk, policy, fingerprint(policy), MappingProxyType(indexed))


def review_option_volatility(view, request, quote):
    """Pure local assessment of a validated native OptionQuote (or explicit absence).

    CLEAR covers only earnings-window/IV evidence checks, never future IV or P&L.
    Neither daily VIX nor an earnings date supplies a contract's implied volatility.
    """
    p, now, risk = view.policy, request.evaluated_at, view.risk
    snapshot = risk.snapshot
    findings, transitions = [], [now + timedelta(seconds=p.max_valid_seconds)]

    def add(state, reason, evidence=()):
        findings.append({"state": state, "reason": reason, "evidence": list(evidence)})

    def transition(at):
        if at > now:
            transitions.append(at)

    current_iv = None
    expires_at = None
    instrument = quote.instrument if quote else None
    if quote is None:
        add("UNKNOWN", "OPTION_QUOTE_MISSING_OR_INVALID")
    elif (
        instrument.instrument_id != request.instrument_id
        or instrument.contract.underlying != request.symbol
        or instrument.contract.underlying_kind != request.underlying_kind
    ):
        add("UNKNOWN", "EXACT_OPTION_INSTRUMENT_REQUIRED")
    else:
        g = quote.greeks
        if instrument.metadata_complete:
            expires_at = instrument.contract.expires_at

        def fresh(e):
            expiry = e.source_at + timedelta(seconds=p.quote_max_age_seconds)
            transition(expiry)
            return (
                e.complete
                and e.entitlement == "REALTIME"
                and e.source_at <= e.received_at <= now < expiry
                and (e.received_at - e.source_at).total_seconds() <= p.max_receive_lag_seconds
            )

        quote_ok = fresh(quote)
        if not instrument.metadata_complete or now >= instrument.contract.last_trading_at:
            quote_ok = False
        transition(instrument.contract.last_trading_at)
        if not quote_ok:
            add("UNKNOWN", "OPTION_QUOTE_STALE_OR_UNUSABLE", (quote.source,))
        if g is None:
            add("UNKNOWN", "CONTRACT_IV_MISSING")
        elif not (
            fresh(g)
            and quote_ok
            and g.instrument == instrument
            and g.source == quote.source
            and g.provenance == "OBSERVED"
            and g.received_at <= quote.received_at
            and abs(g.source_at - quote.source_at).total_seconds() <= p.max_sync_seconds
            and g.implied_volatility is not None
            and g.implied_volatility > 0
        ):
            add("UNKNOWN", "CONTRACT_IV_STALE_OR_UNUSABLE", (g.source,))
        else:
            current_iv = str(g.implied_volatility)

    snapshot_ok = (
        snapshot is not None
        and snapshot.published_at <= now
        and snapshot.policy_hash == risk.policy_hash
    )
    if not snapshot_ok:
        add("UNKNOWN", "EARNINGS_SNAPSHOT_UNAVAILABLE_OR_INVALID")
    elif request.underlying_kind == "EQUITY":
        for issue in snapshot.issues:
            add("UNKNOWN", issue)
        # A clear watch window needs coverage of both the recent post-event tail
        # and the upcoming watch period, even for a short intraday holding horizon.
        lower = now - timedelta(seconds=p.after_seconds)
        upper = request.holding_until + timedelta(seconds=p.before_seconds)
        if expires_at is not None:
            upper = min(upper, expires_at)
        covered = False
        for c in snapshot.coverage:
            if (
                c.dataset != "company.earnings"
                or c.scope != "SYMBOL"
                or request.symbol not in c.symbols
            ):
                continue
            transition(c.fresh_until)
            transition(c.ends_at - timedelta(seconds=p.before_seconds))
            refs = (f"coverage:{c.source}:{c.dataset}", *c.issues)
            if not c.checked_at <= now < c.fresh_until:
                add("UNKNOWN", "EARNINGS_CALENDAR_STALE_OR_FUTURE", refs)
            elif c.status != "COMPLETE":
                add("UNKNOWN", "EARNINGS_COVERAGE_" + c.status, refs)
            elif not c.starts_at <= lower <= upper < c.ends_at:
                add("UNKNOWN", "EARNINGS_WATCH_PERIOD_NOT_COVERED", refs)
            else:
                covered = True
        if not covered:
            add("UNKNOWN", "MISSING_COMPLETE_EARNINGS_COVERAGE")

        starts, items = view.events.get(request.symbol, ((), ()))
        stop = bisect_right(starts, max(request.holding_until, transitions[0]))
        count = 0
        for start, end, item in items[:stop]:
            if end <= now or (expires_at is not None and item.event.starts_at > expires_at):
                continue
            count += 1
            if count > p.max_events:
                add("UNKNOWN", "EARNINGS_ASSESSMENT_CAPACITY")
                break
            e = item.event
            refs = (e.evidence_ref, f"{e.source}:{e.event_id}:{e.revision}")
            transition(start)
            transition(end)
            if item.conflicting:
                add("UNKNOWN", "CONFLICTING_EARNINGS_REVISIONS", refs)
            if not e.complete or e.status != "SCHEDULED" or e.source_at is None:
                add("UNKNOWN", "EARNINGS_DETAILS_INCOMPLETE", refs)
            if start <= now < end or now < start <= request.holding_until:
                add("CAUTION", "EARNINGS_IV_CRUSH_EXPOSURE_POSSIBLE", refs)
            if now <= e.ends_at and e.starts_at <= request.holding_until:
                add("CAUTION", "EARNINGS_INTERVAL_OVERLAPS_HOLDING_PERIOD", refs)

    state = worst(f["state"] for f in findings)
    return {
        "version": "option-event-volatility-v1",
        "policy_version": p.version,
        "policy_hash": view.policy_hash,
        "scope": "SYMBOL",
        "symbol": request.symbol,
        "decision_id": request.decision_id,
        "population_id": request.population_id,
        "evaluated_at": now.isoformat(),
        "valid_until": min(transitions).isoformat(),
        "state": state,
        "findings": findings,
        "current_iv_decimal_fraction": current_iv,
        "earnings_applicable": request.underlying_kind == "EQUITY",
        "crush_forecast_state": "UNKNOWN",
        "expected_iv_drop": None,
        "expected_option_value_change": None,
        "unsupported": ["IV_CRUSH_MAGNITUDE", "IV_TERM_STRUCTURE", "IV_RANK_PERCENTILE"],
        "would_block_new_entries": False,
        "would_restrict_exposure": state != "CLEAR",
        "would_review_held_position": state != "CLEAR",
        "would_restrict_carry": True,
        "mode": "OBSERVATION_ONLY",
        "authority": False,
        "trade_approval": False,
        "live_enabled": False,
    }
