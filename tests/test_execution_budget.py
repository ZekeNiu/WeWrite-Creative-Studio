import asyncio
import json
import httpx
import pytest
from backend import store,models,providers,execution_budget as budget,capabilities,agent_transport


def test_provider_failures_are_metered_without_legacy_request_cap(monkeypatch):
    a=store.create_article();job=store.create_job(a['id'],dict(stage='research',execution_limits={'max_requests':2}))
    original=httpx.AsyncClient;requests=[]
    def respond(req):requests.append(req);return httpx.Response(500,json={'error':'temporary'})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    s=dict(model='mock',name='mock',base_url='https://example.test',secret='mock',protocol='chat')
    async def run():
        token=budget.ACTIVE.set(job['id'])
        try:
            for _ in range(2):
                with pytest.raises(ValueError):await providers.generate(s,'system','prompt')
            with pytest.raises(ValueError):await providers.generate(s,'system','prompt')
        finally:budget.ACTIVE.reset(token)
    asyncio.run(run())
    assert len(requests)==3 and len(store.usage(a['id']))==3
    assert store.job(job['id'])['execution_usage']['unknown']==3


def test_known_and_unknown_costs_are_recorded_without_legacy_cost_cap():
    a=store.create_article();job=store.create_job(a['id'],dict(stage='write',execution_limits={'max_cost':1}))
    service=dict(model='m',input_price=1,output_price=1)
    first=budget.reserve(job['id'],service,fixed=.6)
    second=budget.reserve(job['id'],service,fixed=.6)
    budget.charge(first,dict(status='completed',estimated_cost=.1))
    budget.charge(second,dict(status='unknown',estimated_cost=None))
    third=budget.reserve(job['id'],service,fixed=.01)
    budget.charge(third,dict(status='completed',estimated_cost=.01))
    meter=store.job(job['id'])['execution_usage']
    assert meter['requests']==3 and meter['known_cost']==pytest.approx(.11) and meter['unknown']==1


def test_old_32_request_counter_does_not_block_next_request():
    a=store.create_article();job=store.create_job(a['id'],dict(stage='write',execution_limits={'max_requests':1}))
    store.update_job(job['id'],execution_usage=dict(requests=32,known_cost=0,unknown=0,pending=0))
    record=budget.reserve(job['id'],dict(model='m',name='mock'))
    budget.charge(record,dict(status='unknown',estimated_cost=None))
    assert store.job(job['id'])['execution_usage']['requests']==33


@pytest.mark.parametrize('wrong',[False,True])
def test_capability_requires_actual_tool_result(monkeypatch,wrong):
    calls=[]
    async def turn(service,system,messages,tools):
        calls.append(messages.copy())
        if len(calls)==1:return dict(wire=[dict(role='assistant',content=None)],calls=[dict(id='x',name='connection_probe',arguments='{}')],text='',usage=dict(estimated_cost=None))
        return dict(wire=[],calls=[],text='wrong' if wrong else messages[-1]['content'],usage=dict(estimated_cost=None))
    monkeypatch.setattr(agent_transport,'turn',turn)
    if wrong:
        with pytest.raises(ValueError,match='返回值'):asyncio.run(capabilities.test_tools(dict(model='mock',protocol='chat')))
    else:assert '2 次' in asyncio.run(capabilities.test_tools(dict(model='mock',protocol='chat')))['message']
    assert len(store.usage('connection-tools'))==2
