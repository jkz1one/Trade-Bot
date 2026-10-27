"""Pure local checks. Compile snapshots off the trading path; never refresh here."""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from app.events.models import Assessment, Finding, Policy, Request, Snapshot
from app.options.engine import exact, fingerprint

RANK = {"CLEAR": 0, "CAUTION": 1, "UNKNOWN": 2, "BLOCK_NEW_ENTRIES": 3}


def worst(states):
    return max(states, key=RANK.__getitem__, default="CLEAR")


@dataclass(frozen=True)
class LocalRisk:
    snapshot: Snapshot | None
    policy: Policy
    policy_hash: str
    snapshot_hash: str | None
    samples: object
    events: object


@dataclass(frozen=True)
class CompiledEvent:
    event: object
    key: str
    conflicting: bool
    supported: bool
    start: object
    end: object


def prepare(snapshot: Snapshot | None, policy: Policy) -> LocalRisk:
    """Validation, serialization and indexing belong to a background loader."""
    policy = Policy.model_validate_json(policy.model_dump_json())
    if snapshot is not None:
        snapshot = Snapshot.model_validate_json(snapshot.model_dump_json())
    samples = {}
    for s in snapshot.samples if snapshot else ():
        samples.setdefault(s.instrument_id, []).append(s)
    grouped, indexed = {}, {}
    windows = sorted(policy.windows, key=lambda w: -len(w.category))
    for e in snapshot.events if snapshot else ():
        grouped.setdefault(e.canonical_key or f"{e.source}:{e.event_id}", []).append(e)
    for key, group in grouped.items():
        signatures = {
            (
                e.starts_at,
                e.ends_at,
                e.status,
                e.scope,
                e.symbols,
                e.category,
                e.precision,
                e.importance,
            )
            for e in group
        }
        conflicting = len(signatures) > 1
        for e in group:
            if e.status == "CANCELLED" and not conflicting:
                continue
            w = next(
                (
                    w
                    for w in windows
                    if e.category == w.category or e.category.startswith(w.category + ".")
                ),
                None,
            )
            item = CompiledEvent(
                e,
                key,
                conflicting,
                w is not None,
                e.starts_at - timedelta(seconds=w.before_seconds if w else 0),
                e.ends_at + timedelta(seconds=w.after_seconds if w else 86400),
            )
            for scope in ("*",) if e.scope == "MARKET" else e.symbols:
                indexed.setdefault(scope, []).append(item)
    for scope, items in indexed.items():
        items.sort(key=lambda x: x.start)
        indexed[scope] = (tuple(i.start for i in items), tuple(items))
    return LocalRisk(
        snapshot,
        policy,
        fingerprint(policy),
        fingerprint(snapshot) if snapshot else None,
        MappingProxyType({k: tuple(v) for k, v in samples.items()}),
        MappingProxyType(indexed),
    )


@exact
def assess(view: LocalRisk, request: Request) -> Assessment:
    """Observation only. No IO, network, model, locks, sizing or order operations."""
    p, snapshot, now = view.policy, view.snapshot, request.evaluated_at
    findings = []
    transitions = [now + timedelta(seconds=p.max_assessment_seconds)]

    def add(state, reason, scope="MARKET", evidence=()):
        findings.append(
            Finding(
                state=state,
                reason=reason,
                scope=scope,
                symbols=(request.symbol,) if scope == "SYMBOL" else (),
                evidence=tuple(evidence),
            )
        )

    def transition(t):
        if t > now:
            transitions.append(t)

    if snapshot is None:
        add("UNKNOWN", "SNAPSHOT_UNAVAILABLE")
    elif snapshot.published_at > now or snapshot.policy_hash != view.policy_hash:
        add("UNKNOWN", "SNAPSHOT_TIME_OR_POLICY_MISMATCH")
    else:
        for issue in snapshot.issues:
            add("UNKNOWN", issue)
        for dataset, scope in (
            *((d, "MARKET") for d in p.required_market_datasets),
            *(
                (d, "SYMBOL")
                for d in p.required_company_datasets
                if request.underlying_kind == "EQUITY"
            ),
        ):
            coverage = [
                c
                for c in snapshot.coverage
                if c.dataset == dataset
                and c.scope == scope
                and (scope == "MARKET" or request.symbol in c.symbols)
            ]
            good = False
            for c in coverage:
                transition(c.fresh_until)
                transition(c.ends_at)
                refs = (f"coverage:{c.source}:{c.dataset}",)
                if not c.checked_at <= now < c.fresh_until:
                    add("UNKNOWN", "CALENDAR_STALE_OR_FUTURE", scope, refs)
                elif c.status != "COMPLETE":
                    add("UNKNOWN", "COVERAGE_" + c.status, scope, refs + c.issues)
                elif not c.starts_at <= now <= request.holding_until < c.ends_at:
                    add("UNKNOWN", "HOLDING_PERIOD_NOT_COVERED", scope, refs)
                else:
                    good = True
            if not good:
                add("UNKNOWN", "MISSING_COMPLETE_COVERAGE", scope, (dataset,))

        # All retained windows are evaluated against the caller clock, even when
        # collection has stopped. Old known danger is not erased by stale coverage.
        horizon = max(request.holding_until, transitions[0])
        for scope in ("*", request.symbol):
            starts, items = view.events.get(scope, ((), ()))
            stop = bisect_right(starts, horizon)
            relevant = (item for item in items[:stop] if item.end > now)
            count = 0
            for item in relevant:
                count += 1
                if count > p.max_local_events:
                    add(
                        "UNKNOWN",
                        "ASSESSMENT_EVENT_CAPACITY",
                        "MARKET" if scope == "*" else "SYMBOL",
                    )
                    break
                e, start, end = item.event, item.start, item.end
                if not item.supported:
                    add("UNKNOWN", "UNSUPPORTED_EVENT_CATEGORY", e.scope, (e.evidence_ref,))
                    continue
                if item.conflicting:
                    add("UNKNOWN", "CONFLICTING_EVENT_REVISIONS", e.scope, (item.key,))
                transition(start)
                transition(end)
                if (
                    not e.complete
                    or e.status == "TENTATIVE"
                    or e.source_at is None
                    or e.importance == "UNKNOWN"
                ):
                    add("UNKNOWN", "EVENT_DETAILS_INCOMPLETE", e.scope, (e.evidence_ref,))
                if start <= now < end:
                    add(
                        "BLOCK_NEW_ENTRIES" if e.importance == "HIGH" else "CAUTION",
                        "SCHEDULED_EVENT_WINDOW",
                        e.scope,
                        (e.evidence_ref,),
                    )
                elif now < start <= request.holding_until:
                    add("CAUTION", "EVENT_DURING_HOLDING_PERIOD", e.scope, (e.evidence_ref,))

        day = now.astimezone(ZoneInfo("America/New_York")).date()
        session = next((s for s in snapshot.sessions if s.day == day), None)
        calendar_known = any(
            c.dataset == "session.xnys"
            and c.status == "COMPLETE"
            and c.starts_at <= now < c.ends_at
            and c.checked_at <= now < c.fresh_until
            for c in snapshot.coverage
        )
        if calendar_known:
            if session is None or not session.opens_at <= now < session.closes_at:
                add("BLOCK_NEW_ENTRIES", "OUTSIDE_REGULAR_SESSION", evidence=("session.xnys",))
            else:
                open_end = session.opens_at + timedelta(seconds=p.open_caution_seconds)
                close_start = session.closes_at - timedelta(seconds=p.entry_close_buffer_seconds)
                for t in (open_end, close_start, session.closes_at):
                    transition(t)
                if now < open_end:
                    add("CAUTION", "SESSION_OPEN_WINDOW", evidence=("session.xnys",))
                if now >= close_start:
                    add("BLOCK_NEW_ENTRIES", "SESSION_CLOSE_WINDOW", evidence=("session.xnys",))
                if request.holding_until >= session.closes_at:
                    add("CAUTION", "HORIZON_CROSSES_SESSION_CLOSE", evidence=("session.xnys",))
            if session is not None:
                transition(session.opens_at)

        def stress(samples, scope, identity):
            if len(samples) != 1:
                add("UNKNOWN", "QUOTE_MISSING_OR_CONFLICTING", scope, (identity,))
                return
            s = samples[0]
            ref = (s.evidence_ref,)
            if scope == "SYMBOL" and s.symbol != request.symbol:
                add("UNKNOWN", "QUOTE_SYMBOL_MISMATCH", scope, ref)
                return
            if not s.complete:
                add("UNKNOWN", "QUOTE_INCOMPLETE", scope, ref)
            expires = s.source_at + timedelta(seconds=p.quote_max_age_seconds)
            transition(expires)
            if (
                not s.source_at <= s.received_at <= now < expires
                or (s.received_at - s.source_at).total_seconds() > p.quote_receive_lag_seconds
            ):
                add("UNKNOWN", "QUOTE_STALE_OR_INVALID_CLOCK", scope, ref)
                return
            if s.entitlement != "REALTIME":
                add("UNKNOWN", "QUOTE_ENTITLEMENT_UNCONFIRMED", scope, ref)
            if s.bid is None or s.ask is None or s.bid <= 0 or s.ask < s.bid:
                add("UNKNOWN", "QUOTE_BOOK_UNUSABLE", scope, ref)
                return
            mid = (s.bid + s.ask) / 2
            spread = (s.ask - s.bid) / mid
            prefix = "option" if s.asset == "OPTION" else "stock"
            if spread >= getattr(p, prefix + "_spread_block"):
                add("BLOCK_NEW_ENTRIES", "WIDE_SPREAD", scope, ref)
            elif spread >= getattr(p, prefix + "_spread_caution"):
                add("CAUTION", "ELEVATED_SPREAD", scope, ref)
            if s.bid_size is None or s.ask_size is None:
                add("UNKNOWN", "DISPLAYED_LIQUIDITY_MISSING", scope, ref)
            elif min(s.bid_size, s.ask_size) < p.minimum_displayed_size:
                add("BLOCK_NEW_ENTRIES", "LOW_DISPLAYED_LIQUIDITY", scope, ref)
            if (
                s.reference_at is None
                or s.reference_price is None
                or not (
                    0
                    < (s.source_at - s.reference_at).total_seconds()
                    <= p.reference_max_age_seconds
                )
            ):
                add("UNKNOWN", "PRICE_CHANGE_REFERENCE_MISSING_OR_STALE", scope, ref)
            else:
                move = abs(mid / s.reference_price - 1)
                if move >= p.price_move_block:
                    add("BLOCK_NEW_ENTRIES", "RAPID_PRICE_CHANGE", scope, ref)
                elif move >= p.price_move_caution:
                    add("CAUTION", "ELEVATED_PRICE_CHANGE", scope, ref)

        for symbol in p.market_proxies:
            stress(
                tuple(s for s in snapshot.samples if s.symbol == symbol and s.asset == "STOCK"),
                "MARKET",
                symbol,
            )
        stress(view.samples.get(request.instrument_id, ()), "SYMBOL", request.instrument_id)
        # Reviewed daily VIX is historical context, never relabelled as a live quote.
        if snapshot.volatility:
            add(
                "CAUTION",
                "VOLATILITY_DAILY_ONLY",
                evidence=tuple(v.evidence_ref for v in snapshot.volatility),
            )
            for v in snapshot.volatility:
                if not 0 < (day - v.observed_date).days <= p.volatility_daily_max_age_days:
                    add(
                        "UNKNOWN",
                        "VOLATILITY_DAILY_STALE_OR_UNVERIFIED",
                        evidence=(v.evidence_ref,),
                    )

    market = worst(f.state for f in findings if f.scope == "MARKET")
    symbol = worst(f.state for f in findings if f.scope == "SYMBOL")
    state = worst((market, symbol))
    return Assessment(
        policy_version=p.version,
        policy_hash=view.policy_hash,
        snapshot_sequence=snapshot.sequence if snapshot else None,
        snapshot_hash=view.snapshot_hash,
        request=request,
        state=state,
        market_state=market,
        symbol_state=symbol,
        valid_until=min(transitions),
        findings=tuple(findings),
        unsupported=p.unsupported,
        would_block_new_entries=state == "BLOCK_NEW_ENTRIES",
        would_restrict_exposure=state != "CLEAR",
        would_review_held_position=state != "CLEAR",
        would_restrict_carry=True,  # Current profile forbids carry, including when CLEAR.
    )
