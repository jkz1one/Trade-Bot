"""Original company calendars reach native storage without becoming catalyst clearance."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, UTC
import json
from pathlib import Path

import pytest
from test_earnings_mapping import receipt, FIXTURE
from test_robinhood_read_mapping import schemas as schemas
from test_portfolio_feed import policy, reader

from app.options.earnings_context import CompanyEarningsBinding, from_probe, for_delivery
from app.options.read_capture import CaptureResult
from app.options.input_probe import initial_calls, PINS
from app.options.engine import fingerprint
from app.options.runtime import read_packet
from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
from app.mixed.feed_rollover import validate_policy


def artifact():
    at = datetime.fromisoformat(FIXTURE['started_at'])
    rows = [{'tool': n, 'arguments': a, 'metadata_sha256': PINS[n], 'completed': False}
            for n, a in initial_calls(at)]
    rows[1] = receipt()
    result = CaptureResult(request_id='a'*32, policy_sha256='b'*64, operation='INPUT_PROBE',
                           started_at=at, collected_at=at+timedelta(seconds=10), elapsed_seconds=10,
                           status='FAILED', error_class='InputProbeIncomplete', observations=rows)
    return {'operation': 'input-probe', 'result': result.model_dump(mode='json')}


def binding(target=date(2026, 10, 30)):
    return from_probe(artifact(), target)


def test_original_calendar_binding_is_explicitly_stale_for_next_session():
    raw = artifact(); before = deepcopy(raw)
    bound = from_probe(raw, date(2026, 10, 30))
    view = bound.observation()
    assert raw == before and bound.receipt == raw['result']['observations'][1]
    assert view.record_count == 334 and view.unique_company_quarters == 333
    assert view.issue_counts['CONFLICTING_EVENT_IDENTITY'] == 2
    assert view.coverage == 'OUTSIDE_REQUESTED_WINDOW'
    assert view.entitlement == 'UNKNOWN' and view.provider_updated_at is None
    assert not view.complete_catalyst_coverage and not view.execution_authority
    same = from_probe(raw, date(2026, 10, 29)).observation()
    assert same.coverage == 'PARTIAL_COMPANY_CALENDAR'
    assert len(view.model_dump_json()) < 2000
    assert len(bound.model_dump_json()) < 160*1024


def test_rollover_binds_session_clocks_and_hash_without_changing_legacy_policy():
    base = policy(); legacy = base.model_dump_json(); digest = fingerprint(base)
    proposed = FeedPolicy.model_validate(base.model_dump() | {'company_earnings': binding()})
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    validate_policy(base, proposed, date(2026, 10, 30), now)
    assert fingerprint(proposed) != digest
    assert base.model_dump_json() == legacy and 'company_earnings' not in legacy
    assert fingerprint(FeedPolicy.model_validate_json(legacy)) == digest
    with pytest.raises(ValueError, match='exact reviewed session'):
        validate_policy(base, proposed, date(2026, 11, 2), now)
    with pytest.raises(ValueError, match='available original capture'):
        validate_policy(base, proposed, date(2026, 10, 30), now-timedelta(days=1))
    assert for_delivery(binding(), now) is not None
    assert for_delivery(binding(), now+timedelta(days=1)) is None


@pytest.mark.parametrize('fault', ['future_receipt', 'changed_tool', 'failed_earnings', 'derived_export'])
def test_invalid_original_cannot_enter_session_policy(fault):
    raw = artifact()
    if fault == 'future_receipt': raw['result']['observations'][1]['received_at'] = '2099-01-01T00:00:00Z'
    elif fault == 'changed_tool': raw['result']['observations'][1]['metadata_sha256'] = '0'*64
    elif fault == 'failed_earnings': raw['result']['observations'][1]['completed'] = False
    else: raw['operation'] = 'export-earnings'
    with pytest.raises(ValueError): from_probe(raw, date(2026, 10, 30))


def test_collector_roundtrip_restart_preserves_calendar_without_new_reads(tmp_path, schemas):
    now = datetime(2026, 10, 30, 14, tzinfo=UTC)
    base = policy(); chosen = FeedPolicy.model_validate(base.model_dump() | {'company_earnings': binding()})
    packets = []
    for label, p in [('legacy', base), ('calendar', chosen)]:
        seen = []
        directory = tmp_path / label
        feed = ContinuousFeed(directory, p, schemas, create=True)
        try:
            result = asyncio.run(feed.tick(now=now, reader=reader(now, seen)))
            assert result['status'] == 'DELIVERED'
            packets.append(read_packet(directory / 'feed.json'))
            assert len(seen) == 1 and [c.tool for c in seen[0].calls] == ['get_equity_quotes']
        finally: feed.close()
        original = (directory / 'feed.json').read_bytes()
        feed = ContinuousFeed(directory, p, schemas)
        feed.close()
        assert (directory / 'feed.json').read_bytes() == original
    old, new = packets
    assert new.company_earnings == chosen.company_earnings.observation()
    assert new.frame == old.frame and new.kind == old.kind and new.coverage_issues == old.coverage_issues
    assert old.company_earnings is None


def test_calendar_does_not_change_cycle_or_strategy_catalysts(tmp_path, schemas):
    from test_continuous_strategy_delivery import prepared, capture_for, normalized
    settings, feed, bound, evidence, now = prepared(tmp_path)
    captured, catalog = capture_for(feed, schemas, now)
    baseline = normalized(feed, schemas, captured, catalog, settings, bound, evidence, 1)
    original = receipt()
    original['attempted_at'] = (now-timedelta(seconds=2)).isoformat()
    original['received_at'] = (now-timedelta(seconds=1)).isoformat()
    binding = CompanyEarningsBinding(target_session=now.date(), capture_sha256='a'*64, receipt=original)
    chosen = FeedPolicy.model_validate(feed.model_dump() | {'company_earnings': binding})
    packet = normalized(chosen, schemas, captured, catalog, settings, bound, evidence, 1)
    assert baseline.kind == packet.kind == 'CYCLE'
    assert baseline.frame == packet.frame and baseline.coverage_issues == packet.coverage_issues
    assert packet.company_earnings is not None and not packet.company_earnings.complete_catalyst_coverage


def test_native_runtime_retains_context_and_observer_does_not_revive_old_calendar(tmp_path):
    from test_option_runtime import enable, policy as runtime_policy, step
    from test_option_scope_arbitration import shared
    from app.options.coordinator import DegenFrame
    from app.options.runtime import OptionRuntime
    from app.options.runtime_models import PortfolioRuntimePacket
    from app.mixed.runtime import stored_inputs, stored_company_earnings

    with shared(tmp_path, portfolio=True) as (c, venue, times, _):
        # Shift receipt clocks only for this synthetic runtime test, retaining raw rows.
        source = receipt()
        source['attempted_at'] = (times[0]-timedelta(seconds=2)).isoformat()
        source['received_at'] = (times[0]-timedelta(seconds=1)).isoformat()
        bound = CompanyEarningsBinding(target_session=times[0].date(), capture_sha256='a'*64, receipt=source)
        runtime = OptionRuntime(c, runtime_policy(tmp_path, mixed_inputs='mixed-runtime-inputs-v1',
            scope_inputs='scope-runtime-inputs-v1', simulated_fills='mixed-quote-fills-v1'), create=True)
        enable(runtime)
        for seq in (1, 2):
            packet = PortfolioRuntimePacket(population_id=c.engine.limits.population_id, sequence=seq,
                recorded_at=times[0], kind='MARKET', frame=DegenFrame(portfolio_version='portfolio-frame-v2'),
                company_earnings=bound.observation() if seq == 1 else None)
            path = Path(runtime.policy.feed_file)
            path.write_text(packet.model_dump_json()); path.chmod(0o600)
            asyncio.run(step(runtime))
            with c.engine.journal.read() as db:
                report = stored_inputs(db, times[0])
                shown = stored_company_earnings(db, times[0])
                if seq == 1:
                    assert report['company_earnings']['record_count'] == 334
                    assert shown['delivery_status'] == 'DELIVERED'
                    assert shown['receipt_age_seconds'] >= 1 and shown['current_session']
                    assert not stored_company_earnings(db, times[0]+timedelta(days=1))['current_session']
                else:
                    assert 'company_earnings' not in report and shown is None
            times[0] += timedelta(seconds=1)
        assert venue.submit_count == 0


def test_packet_rejects_false_coverage_and_future_receive_clock():
    from app.options.coordinator import DegenFrame
    from app.options.runtime_models import PortfolioRuntimePacket
    now = datetime(2026, 10, 30, 14, tzinfo=UTC)
    raw = binding().observation().model_dump()
    fields = dict(population_id='test', sequence=1, recorded_at=now, kind='MARKET',
                  frame=DegenFrame(portfolio_version='portfolio-frame-v2'))
    for change in ({'coverage': 'PARTIAL_COMPANY_CALENDAR'}, {'complete_catalyst_coverage': True},
                   {'received_at': now+timedelta(seconds=1)}, {'target_session': date(2026, 11, 2)}):
        with pytest.raises(ValueError): PortfolioRuntimePacket(**fields, company_earnings=raw | change)


def test_existing_owner_rollover_retains_original_calendar_and_refuses_changed_review(tmp_path, schemas):
    from test_feed_rollover import prepared, review, apply
    from test_connected_runtime import digest as files_digest
    from app.mixed.connected_runtime import check

    args, settings, base, proposed = prepared(tmp_path, schemas)
    args = (*args[:-1], date(2026, 10, 30))
    proposal_path = args[-2]
    proposed = FeedPolicy.model_validate(proposed.model_dump() | {'company_earnings': binding()})
    proposal_path.write_text(proposed.model_dump_json())
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    before = files_digest(args[0])
    reviewed = review(args, now)
    assert reviewed['company_earnings']['record_count'] == 334
    assert 'STOCK_EXECUTABLE_SIZES_UNAVAILABLE' in reviewed['entry_blockers']
    assert not reviewed['trading_ready'] and files_digest(args[0]) == before
    modified = proposed.model_dump()
    modified['company_earnings']['capture_sha256'] = 'f'*64
    proposal_path.write_text(FeedPolicy.model_validate(modified).model_dump_json())
    with pytest.raises(ValueError): apply(args, reviewed, now)
    proposal_path.write_text(proposed.model_dump_json())
    applied = apply(args, reviewed, now)
    assert applied['status'] == 'SESSION_ROLLOVER_ENROLLED'
    assert files_digest(args[0]) == before
    feed = ContinuousFeed(args[1], base, schemas)
    try:
        assert feed.policy_for(args[-1]).company_earnings == proposed.company_earnings
        assert feed.policy_for(args[-1]+timedelta(days=1)).company_earnings is None
    finally: feed.close()
    result = check(*args[:4], clock_source=lambda: now)[0]
    assert result['company_earnings'] == reviewed['company_earnings']
    assert not result['trading_ready']
