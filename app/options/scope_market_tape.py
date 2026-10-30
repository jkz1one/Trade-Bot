"""Frozen Scope market observations, without watch mutation or account authority."""

from typing import Literal

from pydantic import model_validator

from app.options.engine import fingerprint
from app.options.governor import _supported
from app.options.models import OptionRecord
from app.options.scope import NY, ScopeSession
from app.options.scope_context import scan_scope_context
from app.options.scope_watch import ScopeWatchPolicy


class ScopeTapePolicy(OptionRecord):
    version: Literal["scope-market-inputs-v1"] = "scope-market-inputs-v1"
    watch: ScopeWatchPolicy
    session: ScopeSession

    @model_validator(mode="after")
    def session_binding(self):
        if self.session.source != self.watch.context.structure.preflight.session_source:
            raise ValueError("Frozen Scope session source required")
        return self


def validate_header(header):
    enrollment = header.scope
    p = enrollment.watch.context.structure.preflight
    s = enrollment.session
    if (
        "SPX" not in header.limits.allowed_underlyings
        or p.provider != header.limits.provider
        or p.quote_source != header.limits.option_source
        or (str(s.session_date), s.opens_at, s.closes_at)
        != (header.session_key, header.opens_at, header.closes_at)
    ):
        raise ValueError("Matching frozen Scope session, universe and owner sources required")


def validate_instrument(header, instrument):
    """Identity, not tradability: stale/blocked evidence may still be recorded."""
    c = instrument.contract
    s = header.scope.session
    if (
        instrument.provider != header.limits.provider
        or not _supported(c)
        or c.underlying != "SPX"
        or c.root != "SPXW"
        or c.underlying_kind != "INDEX"
        or c.settlement_session != "PM"
        or c.expiration != s.session_date
        or c.last_trading_at.astimezone(NY).date() != s.session_date
        or c.last_trading_at < s.protect_at
    ):
        raise ValueError("Exact same-session Scope SPXW identity required")


def _observed(item, source, at):
    if item.source != source or not item.source_at <= item.received_at <= at:
        raise ValueError("Foreign or unavailable Scope evidence")


def validate_scope_event(header, event):
    item = event.frame.scope
    if item is None:
        return
    if header.scope is None:
        raise ValueError("Scope evidence requires frozen Scope tape enrollment")
    f, context, at = item.frame, item.context, event.recorded_at
    p = header.scope.watch.context.structure.preflight
    if f.session is not None and f.session != header.scope.session:
        raise ValueError("Scope observation changed the frozen session or deadlines")
    if len({e.kind for e in f.evidence}) != len(f.evidence) or len(
        {h.symbol for h in f.histories}
    ) != len(f.histories):
        raise ValueError("Duplicate Scope coverage or history identity")
    sources = {s.kind: s.source for s in p.sources}
    histories = {s.symbol: s.source for s in p.history_sources}
    for e in f.evidence:
        _observed(e, sources[e.kind], at)
    for h in f.histories:
        _observed(h, histories[h.symbol], at)
        if any(b.ends_at > min(h.source_at, h.received_at) for b in h.bars):
            raise ValueError("Only completed recorded Scope bars are replayable")
    for value, source in ((f.metadata, p.metadata_source), (f.quote, p.quote_source)):
        if value is not None:
            _observed(value, source, at)
            validate_instrument(header, value.instrument)
    if (
        f.metadata is not None
        and f.quote is not None
        and f.metadata.instrument != f.quote.instrument
    ):
        raise ValueError("Scope metadata and quote identity mismatch")
    instruments = {q.instrument.instrument_id for q in event.frame.quotes}
    if f.quote is not None:
        instruments.add(f.quote.instrument.instrument_id)
    if len(instruments) > 8:
        raise ValueError("Scope and ordinary quotes exceed the common eight-contract bound")
    if f.quote is not None and f.quote.greeks is not None:
        _observed(f.quote.greeks, p.quote_source, f.quote.received_at)
    for value, source in (
        (context.dealer, sources.get("dealer_structure")),
        (context.moves, sources.get("options_analytics")),
        (context.flow, sources.get("options_flow")),
        (context.news, sources.get("broad_market_news")),
        (context.events, sources.get("economic_events")),
        (context.prior, header.scope.watch.context.prior_source),
    ):
        if value is not None:
            _observed(value, source, at)
    if context.previous_session >= header.scope.session.session_date:
        raise ValueError("Scope prior session must precede the recorded session")
    if context.prior is not None and (
        context.prior.session_date != context.previous_session
        or context.prior.closed_at > min(context.prior.source_at, context.prior.received_at)
    ):
        raise ValueError("Only completed matching Scope prior-session evidence is replayable")
    if context.moves is not None and context.moves.expiration != header.scope.session.session_date:
        raise ValueError("Scope expected-move expiration must match the recorded session")
    if item.underlying.symbol != "SPX":
        raise ValueError("Exact Scope underlying required")
    if f.index_reference is not None and f.index_reference != item.underlying:
        raise ValueError("Conflicting Scope frame and current index reference")
    _observed(item.underlying, header.limits.underlying_source, at)
    # Two representations at one receipt must agree; no consumer-specific quote truth.
    for q in event.frame.quotes:
        if (
            f.quote is not None
            and q.instrument.instrument_id == f.quote.instrument.instrument_id
            and q != f.quote
        ):
            raise ValueError("Conflicting common and nested Scope quote")
    for u in event.frame.underlyings:
        if u.symbol == "SPX" and u != item.underlying:
            raise ValueError("Conflicting common and nested Scope underlying")


def replay_scope_context(tape, sequence, *, as_of):
    """Recompute one visible observation at its original clock, never an admission.

    No account, watch receipt, model completion or later observation is substituted.
    Incomplete/stale/blocked payloads retain the existing scanner's diagnostics.
    """
    from app.options.market_tape import RecordedTape

    tape = RecordedTape.model_validate(tape.model_dump(warnings=False))
    if tape.header.scope is None:
        raise ValueError("Frozen Scope tape enrollment required")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Exact positive Scope event sequence required")
    event = next((e for e in tape.available(as_of) if e.sequence == sequence), None)
    if event is None or event.frame.scope is None:
        raise ValueError("Recorded Scope observation not available")
    item = event.frame.scope
    scan = scan_scope_context(
        item.frame, item.context, tape.header.scope.watch.context, now=event.recorded_at
    )
    return {
        "version": "scope-market-context-replay-v1",
        "tape_hash": tape.digest,
        "sequence": sequence,
        "event_hash": fingerprint(event),
        "input_hash": fingerprint(item),
        "policy_hash": fingerprint(tape.header.scope),
        "play_key": item.play_key,
        "recorded_at": event.recorded_at.isoformat(),
        "scan": scan.model_dump(mode="json"),
        "execution_authority": False,
        "live_enabled": False,
    }


def require_legacy_comparison(tapes):
    """Fail before an unconnected consumer can silently discard the Scope family."""
    if any(t.header.scope is not None for t in tapes):
        raise ValueError("Scope tapes require a Scope-aware independent replay/export contract")
