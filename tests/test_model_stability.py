"""Synthetic regressions for the actual tool/search boundary; no paid requests."""
import asyncio
import json
import httpx
import pytest
from backend import agent_transport, providers, store, capabilities, search_tools
from backend.service_errors import ServiceFailure
from backend.execution_budget import BudgetExceeded
from tests.test_native_runtime import article, session


@pytest.fixture
def anyio_backend():return 'asyncio'


@pytest.mark.parametrize('protocol,choice',[('chat','required'),('responses','required'),('anthropic',{'type':'any'})])
def test_runtime_requires_tools_but_probe_can_return_text(protocol,choice):
    s=dict(model='synthetic',protocol=protocol,max_tokens=48000)
    assert agent_transport.request_body(s,'system',[],[])[1]['tool_choice']==choice
    s['_tool_choice']='auto'
    assert agent_transport.request_body(s,'system',[],[])[1]['tool_choice']==({'type':'auto'} if protocol=='anthropic' else 'auto')


@pytest.mark.anyio
async def test_missing_tool_corrected_once_with_context_and_same_budget(monkeypatch):
    s=session(article());turns=[]
    monkeypatch.setattr(providers,'service_for',lambda *_:dict(model='synthetic',protocol='chat'))
    async def turn(service,system,messages,tools):
        turns.append(json.loads(json.dumps(messages)))
        if len(turns)==1:return dict(wire=[dict(role='assistant',content='稍后继续')],calls=[],text='稍后继续',usage={})
        if len(turns)==2:
            calls=[dict(id='write',name='Write',arguments=dict(path=str(s.directory.relative_to(s.home))+'/draft.md',content='完整新稿。'))]
        else:calls=[dict(id='finish',name='Finish',arguments={})]
        return dict(wire=[dict(role='assistant',content=None,tool_calls=[dict(id=c['id'],type='function',function=dict(name=c['name'],arguments=json.dumps(c['arguments']))) for c in calls])],calls=calls,text='',usage={})
    monkeypatch.setattr(agent_transport,'turn',turn)
    result=await s.run()
    assert result['result']=='完整新稿。'
    assert turns[1][-2]['content']=='稍后继续' and '工具' in turns[1][-1]['content']
    j=store.job(s.job_id)
    assert j['execution_usage']['requests']==3 and j['tool_corrections']==1


@pytest.mark.anyio
async def test_repeated_empty_response_stops_without_losing_original(monkeypatch):
    a=article();s=session(a)
    monkeypatch.setattr(providers,'service_for',lambda *_:dict(model='synthetic',protocol='chat'))
    async def empty(*args):return dict(wire=[dict(role='assistant',content='')],calls=[],text='',usage={})
    monkeypatch.setattr(agent_transport,'turn',empty)
    with pytest.raises(ServiceFailure) as caught:await s.run()
    assert caught.value.details['category']=='empty_response'
    assert store.job(s.job_id)['execution_usage']['requests']==2
    assert store.get_article(a['id'])['content']==a['content']


@pytest.mark.anyio
@pytest.mark.parametrize('failure',[ServiceFailure('HTTP failure',category='permission'),BudgetExceeded('cap'),asyncio.CancelledError()])
async def test_search_never_swallows_service_budget_or_cancel(monkeypatch,failure):
    s=session(article());s.search_config.update(enabled=True,allow_fallback=True,browser_enabled=True)
    monkeypatch.setattr(providers,'effective_service',lambda *_:dict(protocol='gemini',model='synthetic'))
    monkeypatch.setattr(s,'reserve',lambda *args:(_ for _ in ()).throw(failure))
    from backend import browser_search
    called=[]
    async def fallback(*args):called.append(True);return []
    monkeypatch.setattr(browser_search,'search',fallback)
    with pytest.raises(type(failure)):await s.search('synthetic')
    assert not called


@pytest.mark.anyio
async def test_tool_internal_budget_failure_ends_session_without_another_model_call(monkeypatch):
    s=session(article());calls=[]
    monkeypatch.setattr(providers,'service_for',lambda *_:dict(model='synthetic',protocol='chat'))
    async def turn(*args):
        calls.append(True)
        return dict(wire=[],calls=[dict(id='search',name='WebSearch',arguments={'query':'test'})],text='',usage={})
    async def limited(*args,**kwargs):raise BudgetExceeded('tool-internal budget exhausted')
    monkeypatch.setattr(agent_transport,'turn',turn);monkeypatch.setattr(s,'search',limited)
    with pytest.raises(BudgetExceeded):await s.run()
    assert len(calls)==1


def test_parameter_changes_invalidate_tools_capability():
    s=dict(model='synthetic',protocol='chat',base_url='https://example.com',max_tokens=8000,temperature=None)
    first=providers.fingerprint(s,'tools')
    assert first!=providers.fingerprint(dict(s,max_tokens=48000),'tools')
    assert first!=providers.fingerprint(dict(s,temperature=.5),'tools')


@pytest.mark.anyio
async def test_correction_cannot_exceed_original_request_cap(monkeypatch):
    s=session(article());s.limits['max_requests']=1;calls=[]
    monkeypatch.setattr(providers,'service_for',lambda *_:dict(model='synthetic',protocol='chat'))
    async def empty(*args):calls.append(True);return dict(wire=[],calls=[],text='',usage={})
    monkeypatch.setattr(agent_transport,'turn',empty)
    with pytest.raises(BudgetExceeded):await s.run()
    assert len(calls)==1


@pytest.mark.anyio
@pytest.mark.parametrize('protocol,payload,category',[
    ('chat',dict(choices=[dict(finish_reason='stop',message=dict(role='assistant',content='',refusal='refused'))]),'refusal'),
    ('responses',dict(status='completed',output=[dict(type='message',content=[dict(type='refusal',refusal='refused')])]),'refusal'),
    ('anthropic',dict(stop_reason='refusal',content=[]),'refusal'),
    ('responses',dict(status='incomplete',incomplete_details={'reason':'max_output_tokens'}),'output_truncated'),
    ('anthropic',dict(stop_reason='max_tokens',content=[]),'output_truncated'),
    ('chat',dict(choices=[dict(finish_reason='tool_calls',message=dict(tool_calls=[dict(id='1',function=dict(name='Read',arguments='{bad'))]))]),'malformed_response'),
    ('chat',{'choices':'broken'},'malformed_response'),
])
async def test_response_errors_never_trigger_tool_correction(monkeypatch,protocol,payload,category):
    s=session(article());calls=[]
    monkeypatch.setattr(providers,'service_for',lambda *_:dict(model='synthetic',protocol=protocol,secret='secret',base_url='https://example.com'))
    async def send(self,request,*args,**kwargs):calls.append(True);return httpx.Response(200,json=payload,request=request)
    monkeypatch.setattr(httpx.AsyncClient,'send',send)
    with pytest.raises(ServiceFailure) as caught:await s.run()
    assert caught.value.details['category']==category
    assert len(calls)==1 and not store.job(s.job_id).get('tool_corrections')


@pytest.mark.anyio
async def test_tool_test_uses_actual_cap_and_allows_second_text(monkeypatch):
    seen=[]
    async def send(self,request,*args,**kwargs):
        body=json.loads(request.content);seen.append(body)
        if len(seen)==1:message=dict(role='assistant',tool_calls=[dict(id='probe',function=dict(name='connection_probe',arguments='{}'))]);reason='tool_calls'
        else:message=dict(role='assistant',content=body['messages'][-1]['content']);reason='stop'
        return httpx.Response(200,json=dict(choices=[dict(finish_reason=reason,message=message)]),request=request)
    monkeypatch.setattr(httpx.AsyncClient,'send',send)
    await capabilities.test_tools(dict(model='synthetic',protocol='chat',max_tokens=48000,temperature=.4,secret='secret',base_url='https://example.com'))
    assert [b['tool_choice'] for b in seen]==['required','auto']
    assert all(b['max_tokens']==48000 and b['temperature']==.4 for b in seen)


@pytest.mark.anyio
async def test_truncated_response_retains_safe_diagnostic_and_known_usage(monkeypatch):
    j=store.create_job('fixture',{'stage':'topic'})
    s=dict(id='s',name='fixture',protocol='chat',model='synthetic',base_url='https://example.com',secret='PRIVATE-KEY',max_tokens=8000,_job_id=j['id'])
    async def send(self,request,*args,**kwargs):
        return httpx.Response(200,json=dict(choices=[dict(finish_reason='length',message=dict(content='unfinished PRIVATE-KEY'))],usage=dict(prompt_tokens=10,completion_tokens=8000)),request=request)
    monkeypatch.setattr(httpx.AsyncClient,'send',send)
    with pytest.raises(ServiceFailure) as caught:await agent_transport.turn(s,'system',[],[])
    assert caught.value.details['category']=='output_truncated'
    assert caught.value.details['response_received'] is True
    assert caught.value.usage['output_tokens']==8000
    d=store.job(j['id'])['response_diagnostic']
    assert d['finish_reason']=='length' and d['parameters']['max_tokens']==8000
    assert 'PRIVATE-KEY' not in json.dumps(d)
