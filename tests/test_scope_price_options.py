"""Price/options Scope is explicit; absent context earns no evidence or points."""
from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_option_scope import AT
from test_option_scope_context import context
from test_option_scope_quality import policy as quality_policy
from test_option_scope_structure import bind, frame

from app.options.scope import PRICE_GROUPS, ScopePreflightPolicy, preflight_scope
from app.options.scope_context import ScopeContextInput
from app.options.scope_quality import ScopeQualityPolicy, scan_scope_quality
from app.options.scope_structure import PRICE_PATTERNS


def inputs(pattern="trap_reversal", right="CALL"):
    f = frame(pattern, right)
    raw = quality_policy(structural_path="completed-spx-plateaus-v2").model_dump()
    preflight = raw["context"]["structure"]["preflight"]
    preflight["input_basis"] = "robinhood-price-options-v1"
    preflight["sources"] = [s for s in preflight["sources"] if s["kind"] in PRICE_GROUPS]
    f = f.model_copy(update={
        "evidence": tuple(e for e in f.evidence if e.kind in PRICE_GROUPS),
        "histories": tuple(h.model_copy(update={"bars": tuple(
            b.model_copy(update={"volume": 0}) for b in h.bars
        )}) for h in f.histories),
    })
    c = ScopeContextInput(previous_session=context(f).previous_session, dealer=None,
                          moves=None, flow=None, news=None, events=None, prior=None)
    return bind(f), c, ScopeQualityPolicy.model_validate(raw)


@pytest.mark.parametrize("pattern", PRICE_PATTERNS)
@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_price_patterns_without_volume_or_invented_context(pattern, right):
    f, c, p = inputs(pattern, right)
    result = scan_scope_quality(f, c, p, now=AT)
    assert not result.issues, result.issues
    assert result.context.structure.vwap is None
    assert len(result.observations) == 8
    assert {o.observation.pattern for o in result.observations} == set(PRICE_PATTERNS)
    for o in result.observations:
        assert o.observation.notes == ("ROBINHOOD_PRICE_OPTIONS_ONLY",)
        assert {x.name for x in o.components} <= {"CROSS_MARKET_CONFIRMATION", "FIRST_TARGET_REWARD"}
        assert all(x.kind != "SESSION_VWAP" for x in o.potential_obstructions)
    selected = next(o for o in result.observations if o.observation.pattern == pattern
                    and o.observation.right == right)
    assert selected.observation.status == "DETECTED", selected.observation.reasons
    assert not result.authority and not result.live_enabled


def test_policy_requires_explicit_variant_and_structural_path():
    _, _, p = inputs()
    raw = p.model_dump()
    raw["structural_path"] = None
    with pytest.raises(ValidationError):
        ScopeQualityPolicy.model_validate(raw)
    raw = p.context.structure.preflight.model_dump()
    del raw["input_basis"]
    with pytest.raises(ValidationError):
        ScopePreflightPolicy.model_validate(raw)


def test_context_and_future_bars_remain_blocked():
    f, c, p = inputs()
    assert scan_scope_quality(f, context(f), p, now=AT).issues
    assert scan_scope_quality(f, c, p, now=AT - timedelta(minutes=5)).issues
    h = f.histories[0]
    h = h.model_copy(update={"bars": (h.bars[0].model_copy(update={"interpolated": True}), *h.bars[1:])})
    assert scan_scope_quality(bind(f.model_copy(update={"histories": (h, *f.histories[1:])})), c, p, now=AT).issues


def test_observed_market_evidence_is_explicit_and_never_context_clearance():
    f, c, p = inputs()
    raw = p.model_dump()
    pf = raw["context"]["structure"]["preflight"]
    for key in ("metadata_source", "quote_source"):
        pf[key] = "robinhood-mcp"
    for source in (*pf["sources"], *pf["history_sources"]):
        source["source"] = "robinhood-mcp"
    p = ScopeQualityPolicy.model_validate(raw)
    common = dict(source="robinhood-mcp", entitlement="UNKNOWN", simulation_basis="ROBINHOOD_OBSERVED_V1")
    f = bind(f.model_copy(update={
        "evidence": tuple(e.model_copy(update=common) for e in f.evidence),
        "histories": tuple(h.model_copy(update=common) for h in f.histories),
        "quote": f.quote.model_copy(update=common), "metadata": f.metadata.model_copy(update=common),
    }))
    assert not scan_scope_quality(f, c, p, now=AT).issues
    q = f.quote.model_copy(update={"simulation_basis": None})
    assert preflight_scope(f.model_copy(update={"quote": q}), p.context.structure.preflight, now=AT).blockers
    e = f.evidence[0].model_dump() | {"kind": "economic_events"}
    with pytest.raises(ValidationError):
        type(f.evidence[0]).model_validate(e)


def test_price_variant_locks_native_watch_and_preserves_frozen_policy(tmp_path):
    from app.execution.engine import ExecutionBlocked
    from app.options.scope_watch import ScopeWatchBook, ScopeWatchPolicy
    from test_option_scope_watch import owned, choice, revision

    f, c, p = inputs()
    watch = ScopeWatchPolicy(context=p.context, quality=p, max_called_plays_per_session=2)
    with owned(tmp_path, enroll=False) as (engine, _, _):
        book = ScopeWatchBook(engine, watch, now=AT, create=True)
        result = book.call('price-only', choice(pattern='trap_reversal'), f, c,
                           expected_revision=revision(engine), now=AT)
        assert result['record']['status'] == 'WATCHING'
        assert result['record']['locked_context']['news'] is None
        assert result['record']['locked_scan']['structure']['vwap'] is None
        reopened = ScopeWatchBook(engine, watch, now=AT)
        assert reopened.policy == watch
        from test_option_scope_watch import policy as legacy_policy
        with pytest.raises(ExecutionBlocked, match='FROZEN_SCOPE_WATCH_POLICY_MISMATCH'):
            ScopeWatchBook(engine, legacy_policy(), now=AT)


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
def test_index_reference_drives_native_unfilled_barrier_without_a_fake_book(tmp_path, right):
    from app.options.models import IndexReference, parse_underlying
    from app.options.scope_watch import ScopeWatchBook, ScopeWatchPolicy
    from app.options.scope_quote import review_quote
    from test_option_scope_watch import owned, choice, revision

    f, c, p = inputs(right=right)
    watch = ScopeWatchPolicy(context=p.context, quality=p, max_called_plays_per_session=2,
                            quote_lifecycle='scope-observed-quotes-v1')
    with owned(tmp_path, enroll=False, underlying_source='robinhood-mcp') as (engine, venue, _):
        book = ScopeWatchBook(engine, watch, now=AT, create=True)
        record = book.call('index-play', choice(right, 'trap_reversal'), f, c,
                          expected_revision=revision(engine), now=AT)['record']
        when = AT + timedelta(seconds=1)
        index = IndexReference(instrument_id='432fbbb8-b82c-454a-852d-eb85382c7066',
            value=record['geometry']['invalidation'], source_at=when, received_at=when,
            original_source_time=when.isoformat(), provider_updated_at=when.isoformat(),
            receipt_sha256='a'*64)
        assert review_quote(record, index, engine.limits, when).status == 'REJECTED'
        old_ledger = engine.journal.report(now=when)['ledger']
        out = book.observe_quote('index-stop', 'index-play', index,
                                expected_revision=revision(engine), now=when)['record']
        assert out['status'] == 'INVALIDATED_UNFILLED'
        saved = out['terminal_quote']['quote']
        assert saved['executable_book'] is False and 'bid' not in saved and 'ask' not in saved
        assert parse_underlying(saved) == index
        assert engine.journal.report(now=when)['ledger'] == old_ledger
        assert venue.submit_count == 0
        assert ScopeWatchBook(engine, watch, now=when).snapshot()['watches'][0]['status'] == 'INVALIDATED_UNFILLED'


def test_index_reference_survives_native_packet_roundtrip():
    from app.options.models import IndexReference
    from app.options.coordinator import DegenFrame
    from app.options.scope_arbitration import ScopeCycleInput
    from app.options.runtime_models import PortfolioRuntimePacket
    f, c, _ = inputs()
    index = IndexReference(instrument_id='432fbbb8-b82c-454a-852d-eb85382c7066', value='102',
        source_at=AT, received_at=AT, original_source_time=AT.isoformat(),
        provider_updated_at=None, receipt_sha256='a'*64)
    frame = DegenFrame(portfolio_version='portfolio-frame-v2',
        scope=ScopeCycleInput(play_key='index-play', frame=f, context=c, underlying=index))
    packet = PortfolioRuntimePacket(population_id='test-index-reference', sequence=1,
        kind='CYCLE', recorded_at=AT, frame=frame)
    again = PortfolioRuntimePacket.model_validate_json(packet.model_dump_json())
    assert isinstance(again.frame.scope.underlying, IndexReference)
    assert 'bid' not in again.frame.scope.underlying.model_dump()


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
def test_price_scope_index_reference_enters_fills_and_closes_native_owner(tmp_path, right):
    import asyncio
    from decimal import Decimal
    from app.options.models import IndexReference
    from app.options.scope_watch import ScopeWatchBook, ScopeWatchPolicy
    from test_option_scope_execution import execution_policy, policy as native_policy, sell
    from test_option_scope_watch import owned, choice, revision, ready
    from test_option_execution import intent_for
    from test_option_scope_observer import observer
    f, context, quality = inputs(right=right)
    f = f.model_copy(update={'metadata': f.metadata.model_copy(update={
        'delta': Decimal('.50') * (1 if right == 'CALL' else -1),
        'greek_provenance': 'OBSERVED', 'volume': 100, 'open_interest': 200})})
    qraw = quality.model_dump()
    qraw['context']['structure']['preflight']['max_history_age_seconds'] = 300
    quality = ScopeQualityPolicy.model_validate(qraw)
    raw = native_policy().model_dump()
    raw['context'], raw['quality'] = quality.context.model_dump(), quality.model_dump()
    raw['contract']['quality'] = quality.model_dump()
    raw['arming']['max_sample_gap_seconds'] = 30
    raw['arming']['sampling_basis'] = 'robinhood-price-options-v1'
    watch = ScopeWatchPolicy.model_validate(raw)
    with owned(tmp_path, enroll=False, underlying_source='robinhood-mcp',
               execution_policy_changes=execution_policy()) as (engine, venue, _):
        book = ScopeWatchBook(engine, watch, now=AT, create=True)
        book.call('first', choice(right, 'trap_reversal'), f, context,
                  expected_revision=revision(engine), now=AT)
        entry_reference = book.snapshot()['watches'][0]['geometry']['reference']
        for seconds in range(0, 61, 10):
            now = AT + timedelta(seconds=seconds)
            ready(engine, venue, now)
            clocks = {'source_at': now, 'received_at': now}
            fresh = f.model_copy(update={
                'index_reference': IndexReference(instrument_id='432fbbb8-b82c-454a-852d-eb85382c7066', value=entry_reference, source_at=now, received_at=now, original_source_time=now.isoformat(), provider_updated_at=None, receipt_sha256='a'*64),
                'metadata': f.metadata.model_copy(update=clocks), 'quote': f.quote.model_copy(update=clocks),
                'evidence': tuple(e if e.kind in {'technical_structure', 'cross_market_agreement'} else e.model_copy(update=clocks) for e in f.evidence)})
            out = book.observe_arming('arming-'+str(seconds), 'first', frame=fresh, context=context,
                                      expected_revision=revision(engine), now=now)
        assert out['record']['arming']['status'] == 'ARMED', out['record']['arming']
        now += timedelta(seconds=1)
        ready(engine, venue, now)
        index = IndexReference(instrument_id='432fbbb8-b82c-454a-852d-eb85382c7066',
            value=entry_reference, source_at=now, received_at=now,
            original_source_time=now.isoformat(), provider_updated_at=None, receipt_sha256='a'*64)
        fresh = fresh.model_copy(update={
            'index_reference': index,
            'metadata': fresh.metadata.model_copy(update={'source_at': now, 'received_at': now}),
            'quote': fresh.quote.model_copy(update={'source_at': now, 'received_at': now}),
            'evidence': tuple(e if e.kind in {'technical_structure', 'cross_market_agreement'} else e.model_copy(update={'source_at': now, 'received_at': now}) for e in fresh.evidence)})
        out = book.review_admission('admit', 'first', frame=fresh, context=context, underlying=index,
                                   expected_revision=revision(engine), now=now)
        assert out['record']['admission_review']['eligible'], out['record']['admission_review'].get('reasons')
        result = book.prepare_entry('first', expected_revision=revision(engine), now=now)
        assert result['status'] == 'PREPARED', result
        buy = intent_for(engine, result['client_id'])
        assert asyncio.run(engine.dispatch(buy.client_id, fresh.quote, index, now=now)) == 'OPEN'
        venue.fill(buy, buy.quantity, fresh.quote, now, fill_id='index-entry-fill', underlying=index)
        assert engine.reconcile(venue.snapshot(now), now=now)['reconciled']
        sell(engine, venue, buy, fresh.quote, index, now)
        result = observer(engine, now).report()
        assert result['status'] == 'OK', result
        assert book.snapshot()['watches'][0]['status'] == 'CLOSED'
