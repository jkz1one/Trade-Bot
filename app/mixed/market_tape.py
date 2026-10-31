"""Separate sealed stock/options/Scope observations, with no account authority."""

from typing import Literal

from pydantic import model_validator

from app.mixed.sources import StockSelectionPolicy
from app.mixed.stock_models import StockLimits
from app.options.market_tape import (
    RecordedTape,
    TapeHeader,
    TapeRecorder,
    _read_records,
    _validate_event,
)


class MixedTapeHeader(TapeHeader):
    version: Literal["mixed-market-tape-v1"] = "mixed-market-tape-v1"
    stocks: StockSelectionPolicy
    stock_limits: StockLimits

    @model_validator(mode="after")
    def mixed_sources(self):
        if (
            self.stocks.paid_selection is not None
            or tuple(i.symbol for i in self.stocks.instruments) != self.setup.symbols
            or self.stock_limits.provider != self.limits.provider
            or any(
                i.provider != self.stock_limits.provider
                or i.symbol not in self.stock_limits.allowed_symbols
                for i in self.stocks.instruments
            )
            or ("SCOPE" in self.stocks.family_priority) != (self.scope is not None)
            or (
                self.swing is not None
                and tuple(f for f in self.stocks.family_priority if f != "SCOPE")
                != self.swing.family_priority
            )
        ):
            raise ValueError(
                "Complete common mixed source policy required; no paid owner authority"
            )
        return self


def validate_event(header, event):
    # The old boundary still rejects shares. Validate its entire option/Scope
    # portion only after the separate mixed header has been explicitly selected.
    if type(header) is not MixedTapeHeader:
        raise ValueError("Explicit mixed tape header required")
    frame = event.frame
    projected = event.model_copy(update={"frame": frame.model_copy(update={"stocks": ()})})
    _validate_event(header, projected)
    if event.kind == "SCOPE" and frame.stocks:
        raise ValueError("Scope-only tape observations cannot carry shares")
    if event.kind != "CYCLE" and any(x.swing or x.catalyst for x in frame.stocks):
        raise ValueError("Only mixed CYCLE observations carry original stock sources")
    instruments = header.stocks.instruments
    quotes = [x.quote for x in frame.stocks]
    if len({q.instrument.instrument_id for q in quotes}) != len(quotes) or any(
        q.instrument not in instruments for q in quotes
    ):
        raise ValueError("Exact unique mixed tape stock identities required")
    if event.kind == "CYCLE" and {q.instrument.instrument_id for q in quotes} != {
        i.instrument_id for i in instruments
    }:
        raise ValueError("Complete common stock quote coverage required")
    for item in frame.stocks:
        q = item.quote
        if (
            q.source != header.stock_limits.quote_source
            or not q.source_at <= q.received_at <= event.recorded_at
        ):
            raise ValueError("Original available stock quote source required")
        if item.swing is not None:
            source, policy = item.swing, header.stocks.swing
            if (
                policy is None
                or source.instrument != q.instrument
                or source.created_at > event.recorded_at
                or source.target_session.isoformat() != header.session_key
            ):
                raise ValueError("Exact enrolled original stock source required")
            for history, expected in (
                (source.history, policy.history_source),
                (source.hourly_history, policy.hourly_source),
            ):
                if history is not None and (
                    history.symbol != q.instrument.symbol
                    or history.source != expected
                    or not history.source_at <= history.received_at <= source.created_at
                    or any(b.closes_at > history.source_at for b in history.bars)
                ):
                    raise ValueError("Original stock history unavailable at source creation")
        if item.catalyst is not None:
            catalyst = item.catalyst
            if (
                header.stocks.swing is None
                or catalyst.symbol != q.instrument.symbol
                or catalyst.source != header.stocks.swing.catalyst_source
                or not catalyst.source_at <= catalyst.received_at <= event.recorded_at
            ):
                raise ValueError("Original available stock catalyst required")


class MixedRecordedTape(RecordedTape):
    header: MixedTapeHeader

    def _validate_event(self, event):
        validate_event(self.header, event)


class MixedTapeRecorder(TapeRecorder):
    header_type = MixedTapeHeader
    validate_event = staticmethod(validate_event)


def load_mixed_tape(path):
    records = _read_records(path)
    return MixedRecordedTape(
        header=records[0]["value"],
        events=tuple(r["value"] for r in records[1:-1]),
        seal=records[-1]["value"],
    )


def validate_series(tapes):
    """Original ordered sessions and one common strategy; no freshened evidence."""
    if not 1 <= len(tapes) <= 60:
        raise ValueError("Bounded mixed session series required")
    tapes = tuple(MixedRecordedTape.model_validate(t.model_dump(warnings=False)) for t in tapes)
    first = tapes[0].header
    previous = None
    for tape in tapes:
        h = tape.header
        fields = (
            "experiment_id",
            "declared_at",
            "limits",
            "setup",
            "selection",
            "swing",
            "stocks",
            "stock_limits",
        )
        if any(getattr(h, key) != getattr(first, key) for key in fields) or (
            (h.scope is None) != (first.scope is None)
            or (h.scope is not None and h.scope.watch != first.scope.watch)
        ):
            raise ValueError("Mixed session series changed its original common policies")
        if previous is not None and (
            h.opens_at <= previous.header.closes_at
            or h.declared_at >= first.opens_at
            or (previous.events and previous.events[-1].recorded_at >= h.opens_at)
        ):
            raise ValueError("Predeclared ordered nonoverlapping mixed sessions required")
        previous = tape
    return tapes
