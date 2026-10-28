"""Versioned mapping persists through native collector recovery without account mutation."""
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_feed import PREOPEN, policy, reader
from test_swing_bar_mapping_proof import synthetic

from app.mixed.continuous_feed import ContinuousFeed, FeedPolicy
from app.mixed.feed_rollover import validate_policy
from app.mixed.swing_feed import SwingHistoryPolicy, snapshot
from app.options.read_capture import CaptureResult
from app.options.read_gateway import CapturePlan


def mapped_policy():
    return policy(swing_history=SwingHistoryPolicy(bar_mapping='utc-day-halfhour-v1'))


def test_legacy_policy_serialization_unchanged():
    assert SwingHistoryPolicy().model_dump()=={
        'version':'preopen-swing-history-v1','daily_bars':56,'hourly_bars':54}
    assert 'bar_mapping' not in SwingHistoryPolicy().model_dump_json()


def test_production_snapshot_uses_same_complete_source(schemas):
    _,_,a=synthetic(schemas)
    h=snapshot(mapped_policy().swing_history,('SPY','QQQ'),schemas,
               CaptureResult.model_validate(a['result']))
    assert len(h.daily[0].bars)==56 and len(h.hourly[0].bars)==54
    assert h.daily[0].entitlement=='UNKNOWN'
    with pytest.raises(ValueError):
        snapshot(SwingHistoryPolicy(),('SPY','QQQ'),schemas,CaptureResult.model_validate(a['result']))


def test_real_placeholders_still_rejected(schemas):
    a=json.loads((Path(__file__).parent/'fixtures/swing_resampled_20261028.json').read_text())['capture']
    a['result']['schemas']=schemas.model_dump(mode='json')
    with pytest.raises(ValueError,match='INTERPOLATED_BAR'):
        snapshot(mapped_policy().swing_history,('SPY','QQQ'),schemas,
                 CaptureResult.model_validate(a['result']))


@pytest.mark.parametrize('bad',[False,True])
def test_native_collector_retains_original_mapping_on_restart(tmp_path,schemas,bad):
    p=mapped_policy();seen=[]
    _,_,a=synthetic(schemas)
    async def capture(cp,*,schemas,plan):
        seen.append(plan)
        market=CapturePlan.model_validate(plan.model_dump()|{'calls':tuple(c for c in plan.calls if not c.label.startswith('swing-'))})
        out=await reader(PREOPEN,[])(cp,schemas=schemas,plan=market)
        if len(plan.calls)>len(market.calls):
            observations=a['result']['observations']
            if bad:
                row=observations[0]['raw']['structuredContent']['data']['results'][0]['bars'][-1]
                row.update(interpolated=True,volume=0)
            out=out.model_copy(update={'plan':plan,'observations':out.observations+observations})
        return out
    with_feed=ContinuousFeed(tmp_path/'feed',p,schemas,create=True)
    try:
        result=asyncio.run(with_feed.tick(now=PREOPEN,reader=capture))
        assert result['status']=='DELIVERED'
        original=with_feed.swing_snapshot(PREOPEN.date())
        assert (original is None)==bad
    finally:with_feed.close()
    reopened=ContinuousFeed(tmp_path/'feed',p,schemas)
    try:
        assert reopened.swing_snapshot(PREOPEN.date())==original
        assert reopened.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==1
    finally:reopened.close()
    with pytest.raises(ValueError):
        ContinuousFeed(tmp_path/'feed',policy(),schemas)


def test_future_session_mapping_change_only():
    original=policy();proposed=mapped_policy()
    validate_policy(original,proposed,date(2026,12,1),PREOPEN)
    changed=FeedPolicy.model_validate(proposed.model_dump()|{'swing_history':{
        **proposed.swing_history.model_dump(),'daily_bars':57}})
    with pytest.raises(ValueError,match='lookbacks'):
        validate_policy(original,changed,date(2026,12,1),PREOPEN)
    with pytest.raises(ValueError,match='future'):
        validate_policy(original,proposed,PREOPEN.date(),PREOPEN)


def test_after_midnight_utc_uses_next_ny_session_policy(tmp_path, schemas, monkeypatch):
    from datetime import UTC, datetime
    at=datetime(2026,11,30,1,tzinfo=UTC)  # November 29 in New York
    feed=ContinuousFeed(tmp_path/'feed',policy(),schemas,create=True)
    selected=[]
    _,expected,a=synthetic(schemas,at=at)
    def effective(target):
        selected.append(target)
        return mapped_policy() if target==date(2026,11,30) else policy()
    monkeypatch.setattr(feed,'policy_for',effective)
    async def capture(cp,*,schemas,plan):
        market=CapturePlan.model_validate(plan.model_dump()|{'calls':(plan.calls[0],)})
        out=await reader(at,[])(cp,schemas=schemas,plan=market)
        assert plan.calls[1:]==expected.calls
        return out.model_copy(update={'plan':plan,'observations':out.observations+a['result']['observations']})
    try:
        assert asyncio.run(feed.tick(now=at,reader=capture))['status']=='DELIVERED'
        assert date(2026,11,29) in selected and date(2026,11,30) in selected
        assert feed.swing_snapshot(date(2026,11,30)) is not None
    finally:feed.close()


def test_reviewed_rollover_persists_mapping_without_touching_owner(tmp_path, schemas, monkeypatch):
    import test_connected_runtime as fixture
    from test_feed_rollover import prepared, review, apply, TARGET
    from app.mixed.feed_rollover import policy_for
    original_configuration=fixture.configuration
    def configured(path):
        settings,feed=original_configuration(path)
        return settings,FeedPolicy.model_validate(feed.model_dump()|{'swing_history':SwingHistoryPolicy()})
    monkeypatch.setattr(fixture,'configuration',configured)
    args,_,base,proposed=prepared(tmp_path,schemas)
    proposed=FeedPolicy.model_validate(proposed.model_dump()|{
        'swing_history':SwingHistoryPolicy(bar_mapping='utc-day-halfhour-v1')})
    args[4].write_text(proposed.model_dump_json())
    before=fixture.digest(args[0])
    reviewed=review(args)
    apply(args,reviewed)
    assert fixture.digest(args[0])==before
    feed=ContinuousFeed(args[1],base,schemas)
    try:
        assert feed.policy_for(TARGET).swing_history.bar_mapping=='utc-day-halfhour-v1'
        assert feed.policy_for(TARGET+timedelta(days=1)).swing_history.bar_mapping=='session-aligned-v1'
    finally:feed.close()
