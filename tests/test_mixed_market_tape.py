"""Explicit common mixed tapes cannot disappear into legacy option consumers."""

import json
from datetime import timedelta

import pytest
from test_degen_options import AT
from test_mixed_native_owner import changed, settings
from test_mixed_selection import quote, source_fixture, stock_frame, stock_policy
from test_option_market_tape import header_for

from app.mixed.market_tape import (
    MixedRecordedTape,
    MixedTapeHeader,
    MixedTapeRecorder,
    load_mixed_tape,
    validate_series,
)
from app.mixed.sources import StockCycleInput
from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.market_tape import RecordedTape, TapeRecorder, load_tape


def header(**kw):
    limits, policy = settings()
    value = header_for().model_dump() | {
        "version": "mixed-market-tape-v1",
        "limits": limits,
        "stock_limits": policy.mixed_owner.stocks,
        "stocks": stock_policy(),
    }
    return MixedTapeHeader.model_validate(value | kw)


def record(path, *, h=None, frame=None):
    with MixedTapeRecorder(path, h or header()) as r:
        r.append(frame or stock_frame(), recorded_at=AT)
        digest = r.seal()
    tape = load_mixed_tape(path)
    assert tape.digest == digest
    return tape


def test_sealed_mixed_tape_preserves_exact_sources_and_recorded_prefix(tmp_path):
    path = tmp_path / "mixed.tape"
    q = quote(AT + timedelta(seconds=1), entitlement="DELAYED")
    with MixedTapeRecorder(path, header()) as r:
        first = r.append(stock_frame(), recorded_at=AT)
        later = r.append(
            DegenFrame(stocks=(StockCycleInput(quote=q),)),
            recorded_at=q.received_at,
            kind="MARKET",
        )
        digest = r.seal()
    tape = load_mixed_tape(path)
    assert tape.digest == digest
    assert tape.available(AT - timedelta(microseconds=1)) == ()
    assert tape.available(AT) == (first,)
    assert tape.available(q.received_at) == (first, later)
    assert tape.events[1].frame.stocks[0].quote == q
    assert validate_series((tape,)) == (tape,)


@pytest.mark.parametrize("consumer", ["model", "reader", "recorder"])
def test_old_tape_consumers_cannot_silently_ignore_shares(tmp_path, consumer):
    path = tmp_path / "mixed.tape"
    tape = record(path)
    with pytest.raises(ValueError):
        if consumer == "model":
            RecordedTape.model_validate(tape.model_dump())
        elif consumer == "reader":
            load_tape(path)
        else:
            TapeRecorder(tmp_path / "old.tape", tape.header)


@pytest.mark.parametrize("damage", ["identity", "source", "clock", "missing", "duplicate"])
def test_mixed_tape_requires_original_available_stock_identity(tmp_path, damage):
    f, q = stock_frame(), quote()
    if damage == "identity":
        q = changed(q, instrument=changed(q.instrument, instrument_id="foreign"))
    elif damage == "source":
        q = changed(q, source="foreign")
    elif damage == "clock":
        q = quote(AT + timedelta(seconds=1))
    stocks = () if damage == "missing" else (StockCycleInput(quote=q),)
    if damage == "duplicate":
        stocks *= 2
    f = changed(f, stocks=stocks)
    with MixedTapeRecorder(tmp_path / "mixed.tape", header()) as r, pytest.raises(ValueError):
        r.append(f, recorded_at=AT)


@pytest.mark.parametrize("damage", ["market_source", "future_history", "future_catalyst", "policy"])
def test_original_stock_bundles_cannot_rewrite_source_clocks(tmp_path, damage):
    source, swing, item, _ = source_fixture()
    h = header(stocks=stock_policy(swing=swing))
    if damage == "future_history":
        source = changed(source, history=changed(source.history, received_at=AT))
        item = changed(item, swing=source)
    elif damage == "future_catalyst":
        item = changed(item, catalyst=changed(item.catalyst, received_at=AT + timedelta(seconds=1)))
    elif damage == "policy":
        h = header()
    f = stock_frame(item=item)
    if damage == "market_source":
        f = DegenFrame(stocks=f.stocks)
    with MixedTapeRecorder(tmp_path / "mixed.tape", h) as r, pytest.raises(ValueError):
        r.append(f, recorded_at=AT, kind="MARKET" if damage == "market_source" else "CYCLE")


@pytest.mark.parametrize("damage", ["event", "seal", "prefix", "permissions"])
def test_mixed_tape_seal_and_private_read_boundary(tmp_path, damage):
    path = tmp_path / "mixed.tape"
    record(path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if damage == "event":
        rows[1]["value"]["frame"]["stocks"][0]["quote"]["bid"] = "599"
    elif damage == "seal":
        rows[-1]["value"]["last_hash"] = "f" * 64
    elif damage == "prefix":
        rows.pop()
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    if damage == "permissions":
        path.chmod(0o644)
    with pytest.raises(ValueError):
        load_mixed_tape(path)


def test_mixed_tape_scope_input_still_requires_explicit_scope_policy(tmp_path):
    from test_option_scope_market_tape import inputs

    _, f = inputs()
    with MixedTapeRecorder(tmp_path / "mixed.tape", header()) as r, pytest.raises(ValueError):
        r.append(DegenFrame(scope=f.scope), recorded_at=AT, kind="SCOPE")


@pytest.mark.parametrize("damage", ["paid", "provider", "universe", "scope"])
def test_common_tape_cannot_claim_native_or_paid_enrollment(damage):
    h = header()
    values = h.model_dump()
    if damage == "paid":
        values["stocks"]["paid_selection"] = "mixed-paid-entry-v1"
    elif damage == "provider":
        values["stock_limits"]["provider"] = "other"
    elif damage == "universe":
        values["stocks"]["instruments"][0]["symbol"] = "QQQ"
    else:
        values["stocks"]["family_priority"] = ("SCOPE", "DEGEN")
    with pytest.raises(ValueError):
        MixedTapeHeader.model_validate(values)


def test_rehashed_future_source_is_rejected_by_complete_tape_validation(tmp_path):
    tape = record(tmp_path / "mixed.tape")
    event = tape.events[0]
    stocks = (StockCycleInput(quote=quote(AT + timedelta(seconds=1))),)
    event = changed(event, frame=changed(event.frame, stocks=stocks))
    with pytest.raises(ValueError):
        MixedRecordedTape(
            header=tape.header,
            events=(event,),
            seal=changed(tape.seal, last_hash=fingerprint(event)),
        )
