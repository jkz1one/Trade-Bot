"""Join verified original Swing sources to current evidence without granting authority."""

from zoneinfo import ZoneInfo

from pydantic import Field

from app.mixed.carry import StockCatalyst
from app.mixed.sources import StockCycleInput
from app.mixed.swing_binding import BoundSwingSources, SwingBindingPolicy
from app.options.coordinator import DegenFrame
from app.options.engine import clock, fingerprint
from app.options.models import OptionRecord
from app.options.selection import ContractMetadata
from app.options.swing import CatalystEvidence, SwingInput
from app.options.swing_batch import SwingBatchInput


class SwingCycleEvidence(OptionRecord):
    """Explicit external evidence; absence never means CLEAR or REALTIME.

    Stock and option policies may enroll different catalyst sources. Keep their
    original records separate even when they refer to the same underlying.
    """

    stocks: tuple[StockCatalyst, ...] = Field(default=(), max_length=2)
    options: tuple[CatalystEvidence, ...] = Field(default=(), max_length=2)


def unique(items, key, label):
    result = {}
    for item in items:
        identity = key(item)
        if identity in result:
            raise ValueError("Duplicate Swing " + label)
        result[identity] = item
    return result


def assemble(frame, bound, policy, metadata, evidence, *, now):
    """Assemble transport inputs, leaving freshness/eligibility to native gates.

    The collector must load `bound` through its original-capture verifier. Missing
    inputs return the untouched market frame and explicit blockers, never a partial
    strategy universe. Supplied UNKNOWN/BLOCKED/stale evidence remains unchanged
    for native rejection. Future/unordered clocks cannot enter a runtime packet.
    This function performs no reads, writes or model calls.
    """
    frame = DegenFrame.model_validate(frame.model_dump())
    policy = SwingBindingPolicy.model_validate(policy.model_dump())
    now = clock(now)
    if (
        frame.swing
        or frame.swing_batches
        or any(s.swing is not None or s.catalyst is not None for s in frame.stocks)
    ):
        raise ValueError("Swing delivery requires an unbound market frame")
    if bound is None:
        return frame, ("SWING_ORIGINAL_SOURCES_UNAVAILABLE",)
    bound = BoundSwingSources.model_validate(bound.model_dump())
    if (
        bound.policy_hash != fingerprint(policy)
        or bound.target_session != now.astimezone(ZoneInfo("America/New_York")).date()
        or bound.created_at > now
    ):
        return frame, ("SWING_ORIGINAL_BINDING_MISMATCH",)
    if bound.status != "PREPARED" or bound.blockers:
        return frame, bound.blockers or ("SWING_ORIGINAL_SOURCES_BLOCKED",)
    symbols = {i.symbol for i in policy.stocks}
    sources = unique(bound.stocks, lambda s: s.instrument.symbol, "stock source")
    originals = unique((*bound.seeds, *bound.batches), lambda s: s.history.symbol, "option source")
    if (
        set(sources) != (symbols if policy.stock_policy is not None else set())
        or set(originals) != (symbols if policy.option_policy is not None else set())
        or any(s.instrument not in policy.stocks for s in sources.values())
        or bool(bound.batches) != bool(policy.option_policy and policy.option_policy.family_batch)
    ):
        return frame, ("SWING_ORIGINAL_SOURCE_COVERAGE_REQUIRED",)
    evidence = SwingCycleEvidence.model_validate((evidence or SwingCycleEvidence()).model_dump())
    stock_cats = unique(evidence.stocks, lambda c: c.symbol, "stock catalyst")
    option_cats = unique(evidence.options, lambda c: c.symbol, "option catalyst")
    if not set(stock_cats) <= set(sources) or not set(option_cats) <= set(originals):
        raise ValueError("Unexpected Swing catalyst subject")
    if any(not c.source_at <= c.received_at <= now for c in (*evidence.stocks, *evidence.options)):
        return frame, ("SWING_CATALYST_UNAVAILABLE_AT_DELIVERY",)
    meta = unique(
        (ContractMetadata.model_validate(m.model_dump()) for m in metadata),
        lambda m: m.instrument.instrument_id,
        "metadata identity",
    )
    books = unique(frame.quotes, lambda q: q.instrument.instrument_id, "quote identity")
    stock_books = unique(frame.stocks, lambda s: s.quote.instrument.symbol, "stock quote")
    issues, stocks, singles, batches = [], [], [], []
    for symbol, source in sources.items():
        item, cat = stock_books.get(symbol), stock_cats.get(symbol)
        if item is None or item.quote.instrument != source.instrument:
            issues.append("SWING_STOCK_QUOTE_UNAVAILABLE:" + symbol)
        if cat is None:
            issues.append("SWING_STOCK_CATALYST_UNAVAILABLE:" + symbol)
        if item is not None and cat is not None:
            stocks.append(StockCycleInput(quote=item.quote, swing=source, catalyst=cat))
    for symbol, original in originals.items():
        cat = option_cats.get(symbol)
        if cat is None:
            issues.append("SWING_OPTION_CATALYST_UNAVAILABLE:" + symbol)
        instruments = original.instruments if bound.batches else (original.instrument,)
        matched = []
        for instrument in instruments:
            identity = instrument.instrument_id
            m, q = meta.get(identity), books.get(identity)
            if (
                instrument not in policy.candidates
                or m is None
                or m.instrument != instrument
                or q is None
                or q.instrument != instrument
            ):
                issues.append("SWING_EXACT_CONTRACT_EVIDENCE_UNAVAILABLE:" + identity)
            else:
                matched.append(m)
        if cat is not None and len(matched) == len(instruments):
            if bound.batches:
                batches.append(
                    SwingBatchInput(seed=original, metadata=tuple(matched), catalyst=cat)
                )
            else:
                singles.append(SwingInput(seed=original, metadata=matched[0], catalyst=cat))
    if issues:
        return frame, tuple(issues)
    return DegenFrame.model_validate(
        frame.model_dump()
        | {
            "stocks": tuple(stocks) if sources else frame.stocks,
            "swing": tuple(singles),
            "swing_batches": tuple(batches),
        }
    ), ()
