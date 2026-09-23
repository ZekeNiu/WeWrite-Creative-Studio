import asyncio
import json
import httpx
import pytest
from backend import store,models,providers,execution_budget as budget,capabilities,agent_transport


def test_provider_failure_and_format_retry_share_limit(monkeypatch):
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
            with pytest.raises(budget.BudgetExceeded):await providers.generate(s,'system','prompt')
        finally:budget.ACTIVE.reset(token)
    asyncio.run(run())
    assert len(requests)==2 and len(store.usage(a['id']))==2
    assert store.job(job['id'])['execution_usage']['unknown']==2


def test_known_cost_reserved_across_pending_requests():
    a=store.create_article();job=store.create_job(a['id'],dict(stage='write',execution_limits={'max_cost':1}))
    service=dict(model='m',input_price=1,output_price=1)
    first=budget.reserve(job['id'],service,fixed=.6)
    with pytest.raises(budget.BudgetExceeded):budget.reserve(job['id'],service,fixed=.6)
    budget.charge(first,dict(status='completed',estimated_cost=.1))
    second=budget.reserve(job['id'],service,fixed=.6)
    budget.charge(second,dict(status='unknown',estimated_cost=None))
    with pytest.raises(budget.BudgetExceeded):budget.reserve(job['id'],service,fixed=.01)
    assert store.job(job['id'])['execution_usage']['requests']==2


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
