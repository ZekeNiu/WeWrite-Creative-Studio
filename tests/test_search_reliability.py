"""Search workflow regressions. Temporary storage and synthetic HTTP only."""
import asyncio
import json

import httpx
import pytest

from backend import agent_transport, browser_search, models, native_runtime, providers, research, search_tools, security, store
from backend.service_errors import SearchEvidenceMissing, ServiceFailure


@pytest.fixture
def setup(monkeypatch):
    cfg = models.Settings().model_dump()
    svc = dict(id='fixture', name='Synthetic', model='deepseek-flash', protocol='anthropic',
               base_url='https://api.deepseek.com/anthropic', secret='dummy', max_tokens=48000,
               input_price=1, output_price=1, search_price=0, currency='CNY')
    cfg.update(services=[svc], default_service='fixture')
    cfg['search'].update(enabled=True, browser_enabled=True, tavily_enabled=True, key_set=True)
    monkeypatch.setattr(providers, 'settings', lambda: cfg)
    monkeypatch.setattr(security, 'key', lambda *_: 'dummy')
    a = store.create_article({'topic': 'Synthetic audit'})
    j = store.create_job(a['id'], {'stage': 'sources', 'revision': a['revision']})
    return cfg, svc, native_runtime.Session(a, j['id'], 'sources', j['request'])


def test_planning_route_does_not_select_search_service(setup):
    cfg, svc, _ = setup
    cfg['services'].append(dict(svc, id='relay', name='Relay', model='synthetic-gemini', protocol='gemini'))
    cfg['routes']['research'] = {'service_id': 'fixture', 'model': ''}
    cfg['search'].update(native_service_id='relay', native_model='synthetic-gemini')
    assert providers.service_for('research')['id'] == 'fixture'
    assert providers.effective_service('search')['id'] == 'relay'


def test_timeout_uses_free_fallback_without_replaying_paid_search(setup, monkeypatch):
    cfg, svc, s = setup
    seen = []
    async def timeout(*args):
        seen.append('native')
        raise ServiceFailure('synthetic timeout', category='timeout')
    async def fallback(*args):
        seen.append('browser')
        return [{'url':'https://example.org'}]
    monkeypatch.setattr(search_tools, 'native', timeout)
    monkeypatch.setattr(browser_search, 'search', fallback)
    s.search_config['allow_fallback'] = True
    assert asyncio.run(s.search('query'))
    assert seen == ['native', 'browser']
    assert store.job(s.job_id)['execution_usage']['requests'] == 1


def test_no_fallback_means_no_fallback_on_later_tool_calls(setup, monkeypatch):
    _, _, s = setup
    async def no_sources(*args):
        raise SearchEvidenceMissing('synthetic no sources')
    async def fallback(*args):
        return [{'url': 'https://example.org'}]
    monkeypatch.setattr(search_tools, 'native', no_sources)
    monkeypatch.setattr(browser_search, 'search', fallback)
    s.search_config['allow_fallback'] = False
    with pytest.raises(SearchEvidenceMissing):
        asyncio.run(s.search('first query'))
    with pytest.raises(ValueError):
        asyncio.run(s.search('second query'))


def test_empty_tavily_results_continue_to_browser(setup, monkeypatch):
    _, _, s = setup
    s.disabled.add('native')
    seen = []
    async def browser(*args):
        seen.append('browser')
        return [{'url': 'https://example.org'}]
    async def tavily(*args):
        seen.append('tavily')
        return []
    monkeypatch.setattr(browser_search, 'search', browser)
    monkeypatch.setattr(providers, 'search', tavily)
    assert asyncio.run(s.search('query'))
    assert seen == ['tavily', 'browser']


def test_failed_search_is_in_persisted_stats(setup, monkeypatch):
    _, _, s = setup
    s.search_config['allow_fallback'] = False
    w = research.Research(s.article, s.job_id, 'research')
    w.cfg['allow_fallback'] = False
    async def timeout(*args):
        raise ServiceFailure('synthetic timeout', category='timeout')
    monkeypatch.setattr(search_tools, 'native', timeout)
    with pytest.raises(ServiceFailure):
        asyncio.run(w.channel('native', 'query'))
    persisted = store.job(s.job_id)['research']
    assert persisted['calls'] == persisted['stats']['search_requests'] == 1


def test_truncated_search_preserves_real_failure_category(setup, monkeypatch):
    _, svc, _ = setup
    async def send(self, request, *args, **kwargs):
        body = json.loads(request.content)
        assert body['max_tokens'] == 48000
        return httpx.Response(200, json=dict(stop_reason='max_tokens', content=[],
            usage=dict(input_tokens=10, output_tokens=2000)), request=request)
    monkeypatch.setattr(httpx.AsyncClient, 'send', send)
    with pytest.raises(ValueError) as caught:
        asyncio.run(search_tools.native(svc, 'query'))
    assert caught.value.details['category'] == 'output_truncated'


def test_search_tool_error_is_distinct_from_empty_results(setup, monkeypatch):
    _, svc, _ = setup
    async def send(self, request, *args, **kwargs):
        return httpx.Response(200, json=dict(stop_reason='end_turn', content=[
            dict(type='server_tool_use', name='web_search', id='s1', input={'query':'q'}),
            dict(type='web_search_tool_result', tool_use_id='s1',
                 content=dict(type='web_search_tool_result_error', error_code='too_many_requests'))
        ]), request=request)
    monkeypatch.setattr(httpx.AsyncClient, 'send', send)
    with pytest.raises(ServiceFailure):
        asyncio.run(search_tools.native(svc, 'query'))


def test_deepseek_chat_preserves_thinking_with_auto_choice():
    svc = dict(model='deepseek-flash', protocol='chat', base_url='https://api.deepseek.com')
    _, body = agent_transport.request_body(svc, 'system', [], native_runtime.TOOLS)
    assert body['tool_choice'] == 'auto'
    assert 'thinking' not in body and 'reasoning_effort' not in body


@pytest.mark.parametrize('category,status',[('authentication',401),('permission',403),('quota',429),
    ('rate_limit_or_quota',429),('invalid_request',400),('refusal',200),('malformed_response',200)])
@pytest.mark.parametrize('engine',['native','research'])
def test_hard_failures_stop_before_other_channels(setup,monkeypatch,category,status,engine):
    _,_,s=setup;calls=[]
    async def fail(*args):
        calls.append('native')
        raise ServiceFailure('Synthetic error',category=category,http_status=status)
    async def forbidden(*args):
        pytest.fail('A protected failure must not switch channels')
    monkeypatch.setattr(search_tools,'native',fail)
    monkeypatch.setattr(browser_search,'search',forbidden)
    monkeypatch.setattr(providers,'search',forbidden)
    w=research.Research(s.article,s.job_id,'research')
    with pytest.raises(ServiceFailure):
        asyncio.run(s.search('q') if engine=='native' else w.channel('native','q'))
    assert calls==['native'] and not store.job(s.job_id).get('free_search_only')


def test_research_transient_error_saves_counts_and_blocks_paid_search_for_job(setup,monkeypatch):
    _,_,s=setup;w=research.Research(s.article,s.job_id,'research');seen=[]
    async def fail(*args):
        seen.append('native');raise ServiceFailure('Synthetic error',category='service_error',http_status=503)
    async def forbidden(*args):pytest.fail('No new paid search allowed after transient error')
    monkeypatch.setattr(search_tools,'native',fail);monkeypatch.setattr(providers,'search',forbidden)
    assert asyncio.run(w.channel('native','q'))==[]
    j=store.job(s.job_id)
    assert j['research']['stats']['search_requests']==j['research']['calls']==1
    assert j['free_search_only'] and j['execution_usage']['unknown']==1
    assert asyncio.run(w.channel('tavily','q'))==[]
    fresh=native_runtime.Session(s.article,s.job_id,'sources',s.request)
    assert fresh.free_search_only
    assert seen==['native'] and j['execution_usage']['requests']==1


def test_empty_browser_advances_through_all_enabled_engines(setup,monkeypatch):
    _,_,s=setup;s.disabled.update(['native','tavily']);seen=[]
    async def empty(query,engine):seen.append(engine);return []
    monkeypatch.setattr(browser_search,'search',empty)
    with pytest.raises(ValueError,match='联网渠道未完成'):asyncio.run(s.search('q'))
    assert seen==['google','bing','baidu','duckduckgo']
    assert store.job(s.job_id)['native_search_count']==4


@pytest.mark.parametrize('protocol,reason',[('anthropic','max_tokens'),('responses','max_output_tokens'),('gemini','MAX_TOKENS')])
def test_truncation_preserves_verified_tool_sources_as_unread_clues(setup,monkeypatch,protocol,reason):
    _,svc,_=setup;svc=dict(svc,protocol=protocol)
    payload={
      'anthropic':dict(stop_reason=reason,content=[dict(type='server_tool_use',name='web_search',id='one'),
          dict(type='web_search_tool_result',tool_use_id='one',content=[dict(type='web_search_result',url='https://example.org')])]),
      'responses':dict(status='incomplete',incomplete_details={'reason':reason},output=[
          dict(type='web_search_call',id='one',status='completed',action={'sources':[{'url':'https://example.org'}]})]),
      'gemini':dict(candidates=[dict(finishReason=reason,groundingMetadata=dict(webSearchQueries=['q'],groundingChunks=[{'web':{'uri':'https://example.org'}}]))])
    }[protocol]
    async def send(self,request,*args,**kwargs):return httpx.Response(200,json=payload,request=request)
    monkeypatch.setattr(httpx.AsyncClient,'send',send)
    rows,meta=asyncio.run(search_tools.native(svc,'q'))
    d=meta['search_diagnostic']
    assert len(rows)==1 and rows[0]['verification_required'] and rows[0]['content']==''
    assert d['source_count']==1 and d['finish_reason']==reason and d['max_tokens']==48000
    assert d['partial'] and any('回复不完整' in warning for warning in d['warnings'])


def test_streamed_search_stop_reason_is_preserved(setup,monkeypatch):
    _,svc,_=setup
    events=[dict(type='message_start',message={'usage':{'input_tokens':10}}),
        dict(type='message_delta',delta={'stop_reason':'max_tokens'},usage={'output_tokens':2000}),dict(type='message_stop')]
    async def send(self,request,*args,**kwargs):
        return httpx.Response(200,text=''.join('data: '+json.dumps(e)+'\n\n' for e in events),
            headers={'content-type':'text/event-stream'},request=request)
    monkeypatch.setattr(httpx.AsyncClient,'send',send)
    with pytest.raises(ServiceFailure) as caught:asyncio.run(search_tools.native(svc,'q'))
    assert caught.value.details['category']=='output_truncated' and caught.value.usage['output_tokens']==2000


def test_truncated_reply_with_tool_error_does_not_keep_sources(setup,monkeypatch):
    _,svc,_=setup
    payload=dict(stop_reason='max_tokens',content=[
        dict(type='server_tool_use',name='web_search',id='good'),
        dict(type='web_search_tool_result',tool_use_id='good',content=[dict(type='web_search_result',url='https://example.org')]),
        dict(type='server_tool_use',name='web_search',id='bad'),
        dict(type='web_search_tool_result',tool_use_id='bad',content=dict(error_code='unavailable'))])
    async def send(self,request,*args,**kwargs):return httpx.Response(200,json=payload,request=request)
    monkeypatch.setattr(httpx.AsyncClient,'send',send)
    with pytest.raises(ServiceFailure) as caught:asyncio.run(search_tools.native(svc,'q'))
    assert caught.value.details['category']=='search_unavailable'
    assert not caught.value.details['search_diagnostic']['partial']


def test_unknown_tool_error_is_not_reflected_or_automatically_recovered(setup,monkeypatch):
    _,svc,_=setup
    payload=dict(content=[dict(type='server_tool_use',name='web_search',id='s'),dict(type='web_search_tool_result',tool_use_id='s',content={'error_code':'PRIVATE-KEY'})])
    async def send(self,request,*args,**kwargs):return httpx.Response(200,json=payload,request=request)
    monkeypatch.setattr(httpx.AsyncClient,'send',send)
    with pytest.raises(ServiceFailure) as caught:asyncio.run(search_tools.native(svc,'q'))
    from backend.search_policy import free_fallback
    assert not free_fallback(caught.value,{'allow_fallback':True})
    assert 'PRIVATE-KEY' not in json.dumps(caught.value.details)
