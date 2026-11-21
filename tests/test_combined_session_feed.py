"""Production-shaped eight-contract session delivery; synthetic prices, no provider calls."""
import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from test_contract_catalog import captures as captures
from test_robinhood_read_mapping import schemas as schemas, envelope, equity, option, history
from test_simulation_session import future_catalog

from app.mixed.continuous_feed import ContinuousFeed
from app.mixed.price_options_profile import proposal as upgrade
from app.mixed.simulation_catalog import proposal
from app.mixed.simulation_profile import configuration
from app.options.read_capture import CaptureResult, policy_digest
from app.options.runtime import read_packet
from app.robinhood.schedule import XNYSCalendar


def combined(captures):
    settings, base = configuration()
    settings = upgrade(settings)[0]
    swing = future_catalog(captures)
    policy, _ = proposal(base, captures[0], captures[1:], date(2026, 10, 28),
                         observed_swing_history=True,
                         swing_contracts=swing[0], swing_samples=swing[1:])
    return settings, policy


def reader(at, *, unusable=False, history_requests=None):
    async def capture(policy, *, schemas, plan):
        observations = []
        for call in plan.calls:
            if call.tool == 'get_equity_quotes':
                rows = []
                for symbol in call.arguments['symbols']:
                    q = equity(symbol)
                    for key in ('venue_bid_time', 'venue_ask_time', 'venue_last_trade_time'):
                        q[key] = at.isoformat()
                    rows.append({'quote': q})
            elif call.tool == 'get_option_quotes':
                rows = [{'quote': option() | {'instrument_id': i, 'updated_at': at.isoformat()}}
                        for i in call.arguments['instrument_ids']]
                if unusable:
                    rows[0]['quote']['updated_at'] = (at + timedelta(minutes=1)).isoformat()
            else:
                assert call.label == 'history'
                if history_requests is not None:
                    history_requests.append(at)
                start = datetime.fromisoformat(call.arguments['start_time'])
                end = datetime.fromisoformat(call.arguments['end_time'])
                template = history()[1]['structuredContent']['data']['results'][0]['bars'][0]
                bars = [template | {'begins_at': (start + timedelta(minutes=5 * i)).isoformat()}
                        for i in range(int((end - start).total_seconds()) // 300)]
                rows = [{'symbol': s, 'interval': '5minute', 'bounds': 'regular', 'bars': bars}
                        for s in call.arguments['symbols']]
            observations.append({'label': call.label, 'tool': call.tool, 'completed': True,
                                 'received_at': (at + timedelta(seconds=1)).isoformat(),
                                 'raw': envelope(rows)})
        return CaptureResult(request_id='a' * 32, policy_sha256=policy_digest(policy),
                             operation='CAPTURE', started_at=at,
                             collected_at=at + timedelta(seconds=1), elapsed_seconds=1,
                             status='COMPLETE', schemas=schemas, plan=plan, observations=observations)
    return capture


def test_transient_unusable_quote_retries_scan_after_restart(tmp_path, captures, schemas):
    settings, policy = combined(captures)
    at = datetime(2026, 10, 28, 15, tzinfo=UTC)
    directory = tmp_path / 'feed'
    history_requests = []
    for index in range(4):
        current = at + timedelta(seconds=policy.poll_seconds * index)
        feed = ContinuousFeed(directory, policy, schemas, create=index == 0)
        try:
            result = asyncio.run(feed.tick(
                now=current, reader=reader(current, unusable=index < 2,
                                           history_requests=history_requests),
                source_settings=settings, window=XNYSCalendar().current_window(current)))
            assert result['status'] == 'DELIVERED'
            packet = read_packet(directory / 'feed.json')
            assert packet.kind == ('CYCLE' if index == 2 else 'MARKET')
            if index < 2:
                assert any(i.startswith('UNUSABLE_OPTION:') for i in packet.coverage_issues)
                assert len(packet.frame.quotes) == 7
            else:
                assert len(packet.frame.quotes) == 8
                assert all(q.source_at == current for q in packet.frame.quotes)
            if index == 2:
                assert packet.frame.histories
        finally:
            feed.close()
    assert len(history_requests) == 3


@pytest.mark.parametrize('capture_failure', [False, True])
def test_scan_retry_cap_preserves_quote_polls_and_resets_next_slot(tmp_path, captures, schemas, capture_failure):
    settings, policy = combined(captures)
    at = datetime(2026, 10, 28, 15, tzinfo=UTC)
    directory = tmp_path / 'feed'
    history_requests = []
    times = [at + timedelta(seconds=policy.poll_seconds * i) for i in range(4)]
    times.append(at + timedelta(minutes=5))
    for index, current in enumerate(times):
        feed = ContinuousFeed(directory, policy, schemas, create=index == 0)
        try:
            async def capture(configuration, *, schemas, plan, index=index, current=current):
                if capture_failure and index < 3:
                    assert any(call.label == 'history' for call in plan.calls)
                    history_requests.append(current)
                    raise OSError('Synthetic unavailable capture')
                return await reader(current, unusable=index < 3,
                                    history_requests=history_requests)(configuration, schemas=schemas, plan=plan)
            result = asyncio.run(feed.tick(
                now=current, reader=capture,
                source_settings=settings, window=XNYSCalendar().current_window(current)))
            if capture_failure and index < 3:
                assert result['status'] == 'FAILED'
            else:
                assert result['status'] == 'DELIVERED'
                packet = read_packet(directory / 'feed.json')
                assert packet.kind == ('CYCLE' if index == 4 else 'MARKET')
                if index == 3:
                    assert len(packet.frame.quotes) == 8
            # Even retrying histories must retain the normal poll limit.
            limited = asyncio.run(feed.tick(now=current + timedelta(seconds=1)))
            assert limited['status'] == 'RATE_LIMITED'
        finally:
            feed.close()
    assert history_requests == times[:3] + times[4:]


@pytest.mark.parametrize('cycle', [False, True])
def test_combined_eight_contracts_deliver_without_optional_swing_history(tmp_path, captures, schemas, cycle):
    settings, policy = combined(captures)
    at = datetime(2026, 10, 28, 15, tzinfo=UTC)
    feed = ContinuousFeed(tmp_path / 'feed', policy, schemas, create=True)
    try:
        result = asyncio.run(feed.tick(now=at, reader=reader(at), source_settings=settings,
                                       window=XNYSCalendar().current_window(at) if cycle else None))
        assert result['status'] == 'DELIVERED'
        packet = read_packet(feed.directory / 'feed.json')
        assert packet.kind == ('CYCLE' if cycle else 'MARKET')
        assert len(packet.frame.quotes) == 8 and len(packet.frame.stocks) == 2
        assert packet.frame.swing_unavailable and not packet.frame.swing_batches
        assert 'SWING_ORIGINAL_SOURCES_UNAVAILABLE' in packet.coverage_issues
        assert 'SCOPE_CURRENT_INPUT_UNAVAILABLE' in packet.coverage_issues
        if cycle:
            assert len(packet.frame.inventories) == 2
            assert sum(len(i.contracts) for i in packet.frame.inventories) == 4
            assert all(h.source_clock_basis == 'COMPLETED_BAR_END' for h in packet.frame.histories)
        assert feed.db.execute('SELECT status FROM attempts').fetchone()[0] == 'DELIVERED'
    finally:
        feed.close()


def test_catalog_capacity_still_rejects_ninth_contract(captures):
    from app.mixed.continuous_feed import FeedPolicy
    from app.mixed.swing_binding import policy_from_settings
    settings, policy = combined(captures)
    candidates = (*policy.candidates, policy.candidates[0])
    with pytest.raises(ValueError):
        FeedPolicy.model_validate(policy.model_dump() | {'candidates': candidates})
    with pytest.raises(ValueError):
        policy_from_settings(settings, candidates)


def test_collector_retains_safe_failure_stage_and_original_capture(tmp_path, captures, schemas, monkeypatch):
    import json
    import app.mixed.continuous_feed as module
    settings, policy = combined(captures)
    at = datetime(2026, 10, 28, 15, tzinfo=UTC)
    directory = tmp_path / 'feed'
    feed = ContinuousFeed(directory, policy, schemas, create=True)
    def reject(*args, **kwargs):
        raise ValueError('PRIVATE_PROVIDER_MESSAGE_DO_NOT_LOG')
    monkeypatch.setattr(module, 'normalize', reject)
    try:
        result = asyncio.run(feed.tick(now=at, reader=reader(at), source_settings=settings))
        assert result['status'] == 'FAILED'
        details = json.loads(feed.db.execute('SELECT details_json FROM attempt_failures').fetchone()[0])
        assert details == result['failure']
        assert details['stage'] == 'NORMALIZE' and details['error_class'] == 'ValueError'
        assert 'PRIVATE_PROVIDER' not in json.dumps(details)
        status, original, packet = feed.db.execute('SELECT status,raw_json,packet_json FROM attempts').fetchone()
        assert status == 'FAILED' and packet is None
        assert json.loads(original)['status'] == 'COMPLETE'
        assert not (directory / 'feed.json').exists()
    finally:
        feed.close()
    feed = ContinuousFeed(directory, policy, schemas)
    try:
        assert json.loads(feed.db.execute('SELECT details_json FROM attempt_failures').fetchone()[0]) == details
        assert feed.db.execute('SELECT raw_json FROM attempts').fetchone()[0] == original
    finally:
        feed.close()
