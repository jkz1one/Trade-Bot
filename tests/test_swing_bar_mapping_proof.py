import copy
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414
from test_swing_feed import policy, reader, PREOPEN
import asyncio

spec = importlib.util.spec_from_file_location(
    "bar_proof", Path(__file__).parents[1] / "scripts/swing-history-bars-proof.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def synthetic(schemas, at=PREOPEN):
    p = policy()
    target, plan = module.plan_for(p, at)
    result = asyncio.run(reader(at, [])(p.capture, schemas=schemas, plan=module.base.plan_for(p, at)[1]))
    raw = result.model_dump(mode="json")
    raw['plan'] = plan.model_dump(mode="json")
    for call, receipt in zip(plan.calls, raw['observations']):
        row = receipt['raw']['structuredContent']['data']['results'][0]
        daily = call.arguments['interval'] == 'day'
        row['interval'] = call.arguments['interval']
        expected = module.windows('day' if daily else 'hour', 56 if daily else 54,
                                  target, module.XNYSCalendar())
        bars=[]
        for start,end in expected:
            if daily:
                labels=[datetime.combine(start.date(), module.time(), UTC)]
            else:
                labels=[]
                while start<end:
                    labels.append(start);start+=timedelta(minutes=30)
            for label in labels:
                bars.append({'begins_at':label.isoformat(),'open_price':'100','high_price':'103',
                             'low_price':'99','close_price':'102','volume':10,'session':'reg'})
        row['bars']=bars
    return p,plan,{'operation':'capture','execution_authority':False,'status':'COMPLETE','result':raw}


def test_exact_half_hours_keep_native_session_hours(schemas):
    p,plan,a=synthetic(schemas)
    report,h=module.inspect_capture(p,plan,a)
    assert report['status']=='CANDIDATE_HISTORY_MAPPED'
    assert all(x.entitlement=='UNKNOWN' for x in h.daily+h.hourly)
    for bar in h.hourly[0].bars:
        assert bar.open==100 and bar.close==102 and bar.high==103 and bar.low==99
        assert bar.volume==(10 if bar.closes_at-bar.begins_at==timedelta(minutes=30) else 20)
    assert not report['collector_mapping_changed'] and not report['trading_ready']


@pytest.mark.parametrize('mutation',['missing','duplicate','shift','interpolation','zero_volume'])
def test_rejects_bad_half_hours(schemas,mutation):
    p,plan,a=synthetic(schemas)
    bars=a['result']['observations'][1]['raw']['structuredContent']['data']['results'][0]['bars']
    if mutation=='missing':bars.pop()
    if mutation=='duplicate':bars[1]=copy.deepcopy(bars[0])
    if mutation=='shift':bars[0]['begins_at']='2026-11-16T15:00:00Z'
    if mutation=='interpolation':bars[0]['interpolated']=True
    if mutation=='zero_volume':bars[0]['volume']=0
    report,h=module.inspect_capture(p,plan,a)
    assert report['status']=='CANDIDATE_HISTORY_MAPPING_UNAVAILABLE' and h is None


def test_original_capture_is_not_repaired_or_restamped(schemas):
    path=Path(__file__).parent/'fixtures/swing_history_20261028.json'
    a=json.loads(path.read_text())['capture'];a['result']['schemas']=schemas.model_dump(mode='json')
    before=copy.deepcopy(a)
    raw=a['result']; p=policy()
    from app.options.read_gateway import CapturePlan
    plan=CapturePlan.model_validate(raw['plan'])
    report,h=module.base.inspect_capture(p,plan,a)
    assert report['status']=='HISTORY_MAPPING_UNAVAILABLE' and h is None
    with pytest.raises(ValueError):module.inspect_capture(p,plan,a)
    assert a==before
    for index in (0,2):
        r=raw['observations'][index]
        with pytest.raises(ValueError,match='coverage'):
            module.map_series(schemas,plan.calls[index],r['raw'],received_at=raw['collected_at'],
                              target=module.instant(raw['collected_at']).date(),count=56)


def test_date_boundaries_are_not_requested_in_future():
    assert module.plan_for(policy(),datetime(2026,10,27,21,tzinfo=UTC))==(None,None)
    target,plan=module.plan_for(policy(),datetime(2026,10,28,1,tzinfo=UTC))
    assert str(target)=='2026-10-28'
    assert plan.calls[0].arguments['start_time'].endswith('T00:00:00+00:00')
    assert plan.calls[0].arguments['end_time']=='2026-10-28T00:00:00+00:00'
    assert plan.calls[1].arguments['interval']=='30minute'


@pytest.mark.parametrize('at',[datetime(2026,11,30,12,tzinfo=UTC),
                              datetime(2026,11,3,12,tzinfo=UTC),
                              datetime(2026,3,10,12,tzinfo=UTC)])
def test_holiday_short_day_and_dst_coverage(schemas,at):
    p,plan,a=synthetic(schemas,at)
    report,h=module.inspect_capture(p,plan,a)
    assert report['status']=='CANDIDATE_HISTORY_MAPPED'
    assert len(h.hourly[0].bars)==54


def test_real_half_hours_pass_but_latest_daily_placeholders_block(schemas):
    path = Path(__file__).parent / 'fixtures/swing_resampled_20261028.json'
    a = json.loads(path.read_text())['capture']
    a['result']['schemas'] = schemas.model_dump(mode='json')
    before = copy.deepcopy(a)
    from app.options.read_gateway import CapturePlan
    plan = CapturePlan.model_validate(a['result']['plan'])
    report, history = module.inspect_capture(policy(), plan, a)
    assert history is None and report['status'] == 'CANDIDATE_HISTORY_MAPPING_UNAVAILABLE'
    validation = report['series_validation']
    assert validation['hourly_bars'] == {'SPY': 54, 'QQQ': 54}
    assert validation['daily_bars'] == {}
    assert [f['label'] for f in validation['failures']] == ['swing-SPY-day', 'swing-QQQ-day']
    assert all(f['reason'] == 'INTERPOLATED_BAR' and
               f['observed_begins_at'] == '2026-10-27T00:00:00+00:00'
               for f in validation['failures'])
    assert a == before
    assert not report['trading_ready'] and report['entitlement'] == 'UNKNOWN'


def test_zero_volume_does_not_become_valid_when_flag_removed(schemas):
    path = Path(__file__).parent / 'fixtures/swing_resampled_20261028.json'
    a = json.loads(path.read_text())['capture']
    a['result']['schemas'] = schemas.model_dump(mode='json')
    for receipt in a['result']['observations'][::2]:
        receipt['raw']['structuredContent']['data']['results'][0]['bars'][-1].pop('interpolated')
    from app.options.read_gateway import CapturePlan
    report, history = module.inspect_capture(policy(), CapturePlan.model_validate(a['result']['plan']), a)
    assert history is None
    assert all(f['reason'] == 'NONPOSITIVE_VOLUME' for f in report['series_validation']['failures'])
