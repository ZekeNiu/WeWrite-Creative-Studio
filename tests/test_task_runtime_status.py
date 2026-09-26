"""Synthetic progress and Windows power-request lifecycle checks."""
import asyncio
import os
import pytest
from backend import execution_budget, power_awake, store, task_progress


def test_streaming_model_call_is_active_until_reply_completes():
    job=store.create_job('synthetic',dict(stage='topic'))
    service=dict(model='synthetic',name='fixture',max_tokens=20,input_price=0,output_price=0)
    seen=[]

    async def emit(chunk):
        seen.append(chunk)
        current=store.job(job['id'])
        assert current['active_request_label']=='模型调用'
        assert current.get('last_completed_at') is None

    async def fake_request(*args):
        await emit('流式片段')
        await asyncio.sleep(.02)
        assert store.job(job['id'])['active_request_started_at']
        return '完整回复',dict(status='completed',estimated_cost=0)

    async def run():
        token=execution_budget.ACTIVE.set(job['id'])
        try:return await execution_budget.text_request(fake_request,service,'system','prompt',emit)
        finally:execution_budget.ACTIVE.reset(token)

    answer,_=asyncio.run(run())
    current=store.job(job['id'])
    assert answer=='完整回复' and seen==['流式片段']
    assert current['active_request_started_at'] is None
    assert current['last_completed_label']=='模型回复已收到' and current['last_completed_at']


@pytest.mark.parametrize('error',[RuntimeError('failed'),asyncio.CancelledError()])
def test_failed_or_cancelled_request_does_not_claim_completion(error):
    job=store.create_job('synthetic',dict(stage='topic'))

    async def run():
        async with task_progress.request(job['id'],'联网检索','检索请求已返回'):
            raise error

    with pytest.raises(type(error)):
        asyncio.run(run())
    current=store.job(job['id'])
    assert current['active_request_started_at'] is None
    assert current.get('last_completed_at') is None


@pytest.mark.skipif(os.name!='nt',reason='Windows execution state only')
def test_power_request_follows_all_active_jobs_and_releases_on_shutdown(monkeypatch):
    calls=[]
    monkeypatch.setattr(power_awake,'set_execution_state',lambda flags:calls.append(flags) or 1)

    async def tick():await asyncio.sleep(.06)

    async def run():
        monitor=asyncio.create_task(power_awake.maintain(.01))
        try:
            await tick()
            assert calls==[]
            first=store.create_job('article',dict(stage='topic'))
            await tick()
            assert calls==[power_awake.ES_CONTINUOUS|power_awake.ES_SYSTEM_REQUIRED]
            store.update_job(first['id'],status='running')
            second=store.create_job('other',dict(stage='source_import'))
            store.update_job(first['id'],status='failed')
            await tick()
            assert len(calls)==1
            store.update_job(second['id'],status='cancelled')
            await tick()
            assert calls[-1]==power_awake.ES_CONTINUOUS
            third=store.create_job('account',dict(stage='account_memory'))
            await tick()
            assert calls[-1]==power_awake.ES_CONTINUOUS|power_awake.ES_SYSTEM_REQUIRED
        finally:
            monitor.cancel()
            await asyncio.gather(monitor,return_exceptions=True)
        assert calls[-1]==power_awake.ES_CONTINUOUS

    asyncio.run(run())


@pytest.mark.skipif(os.name!='nt',reason='Windows execution state only')
def test_real_windows_power_request_is_held_then_cleared():
    async def tick():await asyncio.sleep(.7)

    async def run():
        monitor=asyncio.create_task(power_awake.maintain(.05))
        try:
            job=store.create_job('synthetic',dict(stage='topic'))
            await tick()
            previous=power_awake.set_execution_state(power_awake.ES_CONTINUOUS|power_awake.ES_SYSTEM_REQUIRED)
            assert previous & power_awake.ES_SYSTEM_REQUIRED
            store.update_job(job['id'],status='completed')
            await tick()
            previous=power_awake.set_execution_state(power_awake.ES_CONTINUOUS)
            assert not previous & power_awake.ES_SYSTEM_REQUIRED
        finally:
            monitor.cancel()
            await asyncio.gather(monitor,return_exceptions=True)
            power_awake.set_execution_state(power_awake.ES_CONTINUOUS)

    asyncio.run(run())
