"""Synthetic original sources and pinned-wire routing, without provider/model work."""

import asyncio
from datetime import timedelta

import pytest
from test_option_swing_batch import batch_frame
from test_portfolio_feed import policy as feed_policy
from test_robinhood_read_mapping import AT, envelope, equity, history, instrument, option
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_binding import connected, original
from test_swing_feed import PREOPEN, reader

from app.mixed.carry import StockCatalyst
from app.mixed.continuous_feed import ContinuousFeed, normalize, planned
from app.mixed.sources import StockCycleInput
from app.mixed.stock_models import StockQuote
from app.mixed.swing_binding import bind_sources
from app.mixed.swing_delivery import SwingCycleEvidence, assemble
from app.options.engine import fingerprint
from app.options.read_capture import CaptureResult, policy_digest
from app.options.runtime import read_packet


def fixture():
    snapshot, policy, _ = original()
    bound = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    frame, _ = batch_frame()
    batch = frame.swing_batches[0]
    now = batch.catalyst.received_at
    stock = StockQuote(
        instrument=policy.stocks[0],
        source="fixture-quotes",
        source_at=now,
        received_at=now,
        entitlement="REALTIME",
        complete=True,
        bid="600",
        ask="600.01",
        bid_size=10,
        ask_size=10,
    )
    market = frame.model_copy(
        update={
            "portfolio_version": "portfolio-frame-v2",
            "swing_batches": (),
            "stocks": (StockCycleInput(quote=stock),),
            "quotes": (
                *frame.quotes,
                frame.quotes[-1].model_copy(
                    update={
                        "instrument": batch.seed.instruments[1],
                    }
                ),
            ),
        }
    )
    evidence = SwingCycleEvidence(
        stocks=(StockCatalyst.model_validate(batch.catalyst.model_dump()),),
        options=(batch.catalyst,),
    )
    return market, bound, policy, batch.metadata, evidence, now


def test_exact_native_batch_and_stock_inputs_keep_every_original_byte():
    frame, bound, policy, metadata, evidence, now = fixture()
    before = [x.model_dump_json() for x in (frame, bound, policy, evidence)]
    result, issues = assemble(frame, bound, policy, metadata, evidence, now=now)
    assert not issues
    assert result.swing_batches[0].seed == bound.batches[0]
    assert result.swing_batches[0].metadata == metadata
    assert result.stocks[0].swing == bound.stocks[0]
    assert result.stocks[0].catalyst == evidence.stocks[0]
    assert result.quotes == frame.quotes and result.inventories == frame.inventories
    assert before == [x.model_dump_json() for x in (frame, bound, policy, evidence)]


@pytest.mark.parametrize("damage", ["absent", "blocked", "policy", "session", "future", "coverage"])
def test_wrong_original_never_partially_assembles_a_strategy_frame(damage):
    frame, bound, policy, metadata, evidence, now = fixture()
    if damage == "absent":
        bound = None
    elif damage == "blocked":
        bound = bound.model_copy(update={"status": "BLOCKED", "blockers": ("UNKNOWN",)})
    elif damage == "policy":
        policy = policy.model_copy(update={"runtime_hash": "c" * 64})
    elif damage == "session":
        now += timedelta(days=1)
    elif damage == "future":
        bound = bound.model_copy(update={"created_at": now + timedelta(seconds=1)})
    else:
        bound = bound.model_copy(update={"stocks": ()})
    result, issues = assemble(frame, bound, policy, metadata, evidence, now=now)
    assert issues and result == frame


@pytest.mark.parametrize("damage", ["catalyst", "metadata", "quote", "identity", "stock"])
def test_missing_current_evidence_keeps_all_market_books(damage):
    frame, bound, policy, metadata, evidence, now = fixture()
    if damage == "catalyst":
        evidence = None
    elif damage == "metadata":
        metadata = metadata[:1]
    elif damage == "quote":
        frame = frame.model_copy(update={"quotes": frame.quotes[:-1]})
    elif damage == "identity":
        metadata = (metadata[0].model_copy(update={"instrument": metadata[1].instrument}),)
    else:
        frame = frame.model_copy(update={"stocks": ()})
    result, issues = assemble(frame, bound, policy, metadata, evidence, now=now)
    assert issues and result == frame
    assert not result.swing_batches and not result.swing


@pytest.mark.parametrize("damage", ["duplicate", "unexpected"])
def test_catalyst_subjects_cannot_be_selected_by_list_order(damage):
    frame, bound, policy, metadata, evidence, now = fixture()
    items = (
        evidence.options * 2
        if damage == "duplicate"
        else (evidence.options[0].model_copy(update={"symbol": "QQQ"}),)
    )
    evidence = evidence.model_copy(update={"options": items})
    with pytest.raises(ValueError, match="Duplicate|Unexpected"):
        assemble(frame, bound, policy, metadata, evidence, now=now)


@pytest.mark.parametrize("damage", ["UNKNOWN", "BLOCKED", "stale", "future", "source", "horizon"])
def test_supplied_ineligible_catalyst_is_preserved_and_native_scan_blocks_it(damage):
    from test_option_entry_coordination import policies

    from app.options.degen import scan_degen
    from app.options.swing import SwingInput, scan_swing
    from app.options.swing_batch import batch_seeds, family_policy
    from app.robinhood.schedule import XNYSCalendar

    frame, bound, policy, metadata, evidence, now = fixture()
    cat = evidence.options[0]
    change = (
        {"status": damage}
        if damage in {"UNKNOWN", "BLOCKED"}
        else {
            "stale": {"source_at": now - timedelta(minutes=2)},
            "future": {
                "source_at": now + timedelta(seconds=1),
                "received_at": now + timedelta(seconds=1),
            },
            "source": {"source": "wrong-source"},
            "horizon": {"valid_through": now},
        }[damage]
    )
    cat = cat.model_copy(update=change)
    evidence = evidence.model_copy(update={"options": (cat,)})
    result, issues = assemble(frame, bound, policy, metadata, evidence, now=now)
    if damage == "future":
        assert issues == ("SWING_CATALYST_UNAVAILABLE_AT_DELIVERY",) and result == frame
        return
    assert not issues and result.swing_batches[0].catalyst == cat
    calendar = XNYSCalendar()
    setup, _ = policies()
    h = result.histories[0]
    intraday = scan_degen(h, setup, calendar.current_window(now), now=now)
    child = batch_seeds(bound.batches[0], policy.option_policy, calendar, ("SPY",))[0]
    scan = scan_swing(
        SwingInput(seed=child, metadata=metadata[0], catalyst=cat),
        family_policy(child, policy.option_policy),
        intraday,
        h,
        calendar,
        ("SPY",),
        now=now,
        receive_lag=5,
    )
    assert "SWING_CATALYST_CLEARANCE_REQUIRED" in scan.observations[0].reasons


def captured_market(schemas, p=None):
    p = p or feed_policy()
    first = instrument()
    # Distinct reviewed catalog identities, one same-day and one later expiry.
    first = first.model_copy(
        update={
            "contract": first.contract.model_copy(
                update={
                    "expiration": AT.date(),
                    "last_trading_at": AT.replace(hour=20, minute=0),
                    "expires_at": AT.replace(hour=21, minute=0),
                    "settles_at": AT.replace(hour=21, minute=0) + timedelta(days=1),
                }
            )
        }
    )
    later = first.model_copy(
        update={
            "instrument_id": "later-contract",
            "contract": first.contract.model_copy(
                update={
                    "expiration": AT.date() + timedelta(days=7),
                    "last_trading_at": first.contract.last_trading_at + timedelta(days=7),
                    "expires_at": first.contract.expires_at + timedelta(days=7),
                    "settles_at": first.contract.settles_at + timedelta(days=7),
                }
            ),
        }
    )
    held = later.model_copy(update={"instrument_id": "held-contract"})
    p = p.model_copy(update={"candidates": (first, later)})
    at = AT + timedelta(minutes=30)
    from app.robinhood.schedule import XNYSCalendar

    plan, catalog = planned(p, (held,), at, XNYSCalendar().current_window(at), cycle=True)
    _, raw_history = history()
    row = raw_history["structuredContent"]["data"]["results"][0]
    raw_history = envelope([row | {"symbol": i.symbol} for i in p.stocks])
    observations = []
    for c in plan.calls:
        raw = (
            raw_history
            if c.tool == "get_equity_historicals"
            else envelope(
                [{"quote": equity(i.symbol)} for i in p.stocks]
                if c.tool == "get_equity_quotes"
                else [
                    {"quote": option() | {"instrument_id": i}}
                    for i in c.arguments["instrument_ids"]
                ]
            )
        )
        observations.append({"label": c.label, "tool": c.tool, "completed": True, "raw": raw})
    captured = CaptureResult(
        request_id="b" * 32,
        policy_sha256=policy_digest(p.capture),
        operation="CAPTURE",
        started_at=at,
        collected_at=at + timedelta(seconds=2),
        elapsed_seconds=2,
        status="COMPLETE",
        schemas=schemas,
        plan=plan,
        observations=observations,
    )
    return p, captured, catalog, held


def test_mixed_expiries_route_same_day_inventory_and_keep_swing_and_held_books(schemas):
    p, capture, catalog, held = captured_market(schemas)
    packet = normalize(p, schemas, capture, catalog, (held,), sequence=1, now=capture.collected_at)
    assert packet.kind == "CYCLE" and not packet.coverage_issues
    assert len(packet.frame.inventories) == 1
    assert tuple(m.instrument for m in packet.frame.inventories[0].contracts) == p.candidates[:1]
    assert tuple(q.instrument for q in packet.frame.quotes) == p.candidates
    assert packet.frame.held_quotes[0].instrument == held
    assert all(q.entitlement == "UNKNOWN" for q in packet.frame.quotes)


def test_collector_delivers_persisted_blockers_after_restart_without_erasing_quotes(
    tmp_path, schemas
):
    settings, policy = connected(tmp_path)
    feed = ContinuousFeed(tmp_path / "feed", policy, schemas, create=True)
    try:
        assert (
            asyncio.run(
                feed.tick(now=PREOPEN, reader=reader(PREOPEN, []), source_settings=settings)
            )["status"]
            == "DELIVERED"
        )
        first = read_packet(feed.directory / "feed.json")
        assert first.coverage_issues == ("SWING_ORIGINAL_SOURCES_UNAVAILABLE",)
        feed.bind_swing_sources(settings, now=PREOPEN + timedelta(seconds=2))
    finally:
        feed.close()
    feed = ContinuousFeed(tmp_path / "feed", policy, schemas)
    try:
        at = PREOPEN + timedelta(seconds=10)
        assert (
            asyncio.run(feed.tick(now=at, reader=reader(at, []), source_settings=settings))[
                "status"
            ]
            == "DELIVERED"
        )
        packet = read_packet(feed.directory / "feed.json")
        assert packet.kind == "MARKET" and len(packet.frame.stocks) == 2
        assert set(packet.coverage_issues) == {
            "SWING_HISTORY_ENTITLEMENT_REQUIRED:SPY",
            "SWING_HISTORY_ENTITLEMENT_REQUIRED:QQQ",
        }
        retained = fingerprint(packet)
    finally:
        feed.close()
    feed = ContinuousFeed(tmp_path / "feed", policy, schemas)
    try:
        assert fingerprint(read_packet(feed.directory / "feed.json")) == retained
    finally:
        feed.close()


def test_missing_swing_inputs_preserve_other_cycle_and_held_quotes(tmp_path, schemas):
    settings, p = connected(tmp_path)
    p, capture, catalog, held = captured_market(schemas, p)
    plain = normalize(p, schemas, capture, catalog, (held,), sequence=1, now=capture.collected_at)
    assert plain.kind == "CYCLE"
    packet = normalize(
        p,
        schemas,
        capture,
        catalog,
        (held,),
        sequence=1,
        now=capture.collected_at,
        source_settings=settings,
    )
    assert packet.kind == "CYCLE"
    assert packet.frame.swing_unavailable
    assert packet.coverage_issues == ("SWING_ORIGINAL_SOURCES_UNAVAILABLE",)
    assert packet.frame.held_quotes == plain.frame.held_quotes
    assert packet.frame.quotes == plain.frame.quotes
    assert packet.frame.stocks == plain.frame.stocks
    assert packet.frame.histories == plain.frame.histories
    assert packet.frame.inventories == plain.frame.inventories


def test_single_seed_delivery_keeps_original_derived_targets():
    frame, _, policy, metadata, evidence, now = fixture()
    snapshot, _, _ = original()
    p = policy.option_policy.model_dump()
    p.update(family_batch=None, daily_base=None, higher_levels=None)
    p["ma_pullback"]["periods"] = (8,)
    from app.mixed.swing_binding import SwingBindingPolicy

    policy = SwingBindingPolicy.model_validate(
        policy.model_dump()
        | {
            "option_policy": p,
            "candidates": policy.candidates[:1],
        }
    )
    bound = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    result, issues = assemble(frame, bound, policy, metadata[:1], evidence, now=now)
    assert not issues and not result.swing_batches
    assert result.swing[0].seed == bound.seeds[0]
    assert result.swing[0].seed.target_geometry is not None
    assert result.swing[0].seed.first_target == bound.seeds[0].target_geometry.targets[0]


def test_two_underlyings_keep_independent_sources_and_catalysts():
    frame, _, policy, metadata, evidence, now = fixture()
    snapshot, _, _ = original()
    stock = policy.stocks[0].model_copy(update={"symbol": "QQQ", "instrument_id": "qqq-stock"})
    options = tuple(
        i.model_copy(
            update={
                "instrument_id": "qqq-" + i.instrument_id,
                "contract": i.contract.model_copy(update={"underlying": "QQQ", "root": "QQQ"}),
            }
        )
        for i in policy.candidates
    )
    policy = policy.model_copy(
        update={"stocks": (*policy.stocks, stock), "candidates": (*policy.candidates, *options)}
    )
    snapshot = snapshot.model_copy(
        update={
            "daily": (*snapshot.daily, snapshot.daily[0].model_copy(update={"symbol": "QQQ"})),
            "hourly": (*snapshot.hourly, snapshot.hourly[0].model_copy(update={"symbol": "QQQ"})),
        }
    )
    bound = bind_sources(snapshot, policy, created_at=snapshot.captured_at)
    assert bound.status == "PREPARED", bound.blockers
    frame = frame.model_copy(
        update={
            "stocks": (
                *frame.stocks,
                StockCycleInput(
                    quote=frame.stocks[0].quote.model_copy(update={"instrument": stock})
                ),
            ),
            "quotes": (
                *frame.quotes,
                *(frame.quotes[-1].model_copy(update={"instrument": i}) for i in options),
            ),
        }
    )
    metadata = (
        *metadata,
        *(m.model_copy(update={"instrument": i}) for m, i in zip(metadata, options)),
    )
    evidence = evidence.model_copy(
        update={
            "stocks": (
                *evidence.stocks,
                evidence.stocks[0].model_copy(update={"symbol": "QQQ", "status": "UNKNOWN"}),
            ),
            "options": (
                *evidence.options,
                evidence.options[0].model_copy(update={"symbol": "QQQ", "status": "BLOCKED"}),
            ),
        }
    )
    result, issues = assemble(frame, bound, policy, metadata, evidence, now=now)
    assert not issues and len(result.stocks) == len(result.swing_batches) == 2
    assert tuple(s.catalyst for s in result.stocks) == evidence.stocks
    assert tuple(s.catalyst for s in result.swing_batches) == evidence.options
    assert tuple(s.seed for s in result.swing_batches) == bound.batches


def test_diagnostics_do_not_discard_protection_books_when_more_than_ten_reasons(schemas):
    p, capture, catalog, held = captured_market(schemas)
    reasons = tuple("MISSING_REQUIRED_INPUT_" + str(i) for i in range(32))
    packet = normalize(
        p,
        schemas,
        capture,
        catalog,
        (held,),
        sequence=1,
        now=capture.collected_at,
        history_issues=reasons,
    )
    assert packet.kind == "MARKET" and packet.coverage_issues == reasons
    assert packet.frame.held_quotes[0].instrument == held
    assert len(packet.frame.stocks) == 2


def test_oversized_strategy_packet_retains_readable_protection_delivery(tmp_path):
    from app.mixed.continuous_feed import bounded_delivery
    from app.options.runtime import MAX_PACKET_BYTES
    from app.options.runtime_models import PortfolioRuntimePacket

    frame, bound, policy, metadata, evidence, now = fixture()
    frame, issues = assemble(frame, bound, policy, metadata, evidence, now=now)
    assert not issues
    # Capacity-only stress fixture. Native source validation is tested separately;
    # repeated bars deliberately model worst-case serialized lookback size here.
    source = frame.stocks[0].swing
    history = source.history.model_copy(update={"bars": (source.history.bars * 5)[:260]})
    hourly = source.hourly_history.model_copy(
        update={"bars": (source.hourly_history.bars * 5)[:260]}
    )
    source = source.model_copy(update={"history": history, "hourly_history": hourly})
    batch = frame.swing_batches[0]
    batch = batch.model_copy(
        update={
            "seed": batch.seed.model_copy(
                update={
                    "history": batch.seed.history.model_copy(update={"bars": history.bars}),
                    "hourly_history": hourly,
                }
            )
        }
    )
    frame = frame.model_copy(
        update={
            "stocks": (frame.stocks[0].model_copy(update={"swing": source}),) * 2,
            "swing_batches": (batch,) * 2,
        }
    )
    packet = PortfolioRuntimePacket(
        population_id="capacity-fixture", sequence=1, recorded_at=now, kind="CYCLE", frame=frame
    )
    assert len(packet.model_dump_json().encode()) > MAX_PACKET_BYTES
    result = bounded_delivery(packet)
    assert result.kind == "MARKET" and result.coverage_issues == (
        "RUNTIME_STRATEGY_PACKET_CAPACITY",
    )
    assert result.frame.quotes == packet.frame.quotes
    assert tuple(s.quote for s in result.frame.stocks) == tuple(
        s.quote for s in packet.frame.stocks
    )
    assert not result.frame.histories and not result.frame.swing_batches
    destination = tmp_path / "feed.json"
    destination.write_text(result.model_dump_json())
    destination.chmod(0o600)
    assert read_packet(destination) == result
