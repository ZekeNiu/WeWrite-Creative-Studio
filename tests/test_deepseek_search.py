"""Focused v2.3.3 regressions; synthetic HTTP only."""
import asyncio
import hashlib
import json
import httpx
import pytest
from backend import providers, search_tools, store, capabilities
from backend.service_errors import ServiceFailure, SearchEvidenceMissing
from tests.test_research import client, H


def service(base='https://api.deepseek.com/anthropic'):
    return dict(id='s', name='模拟官方服务', model='deepseek-flash', protocol='anthropic',
                base_url=base, secret='fixture-secret', max_tokens=48000, temperature=None,
                input_price=1, output_price=2, search_price=0, currency='CNY')


def response(ids=('one',), repeats=1, sources=True):
    blocks=[]
    for ident in ids:
        blocks.append(dict(type='server_tool_use', id=ident, name='web_search'))
        blocks.extend([dict(type='web_search_tool_result', tool_use_id=ident,
                           content=[dict(type='web_search_result', url='https://example.org/'+ident)] if sources else [])]*repeats)
    return dict(content=blocks, usage=dict(input_tokens=100, output_tokens=20))


def network(monkeypatch, payload, status=200):
    real=httpx.AsyncClient;seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(status,json=payload)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    return seen


@pytest.mark.parametrize('base',['https://api.deepseek.com','https://api.deepseek.com/v1',
                               'https://api.deepseek.com/anthropic','https://api.deepseek.com/anthropic/v1'])
def test_official_directory_and_messages_have_separate_paths(base):
    assert providers.endpoint(base,'models')=='https://api.deepseek.com/v1/models'
    assert providers.endpoint(base,'messages')=='https://api.deepseek.com/anthropic/v1/messages'
    assert providers.endpoint(base,'chat/completions')=='https://api.deepseek.com/v1/chat/completions'


@pytest.mark.parametrize('base',['https://relay.example/anthropic','https://api.deepseek.com.evil.example/anthropic'])
def test_relay_address_never_rewritten_to_official(base):
    assert providers.endpoint(base,'models')==base+'/v1/models'
    assert providers.endpoint(base,'messages')==base+'/v1/messages'


def test_official_model_directory_real_request_path(monkeypatch):
    seen=network(monkeypatch,{'data':[{'id':'deepseek-flash'}]})
    assert asyncio.run(providers.list_models(service()))==['deepseek-flash']
    assert str(seen[0].url)=='https://api.deepseek.com/v1/models'


def test_duplicate_results_are_one_tool_call(monkeypatch):
    network(monkeypatch,response(repeats=2))
    rows,meta=asyncio.run(search_tools.native(service('https://relay.example'),'q'))
    assert len(rows)==1 and meta['calls']==1
    d=meta['search_diagnostic']
    assert (d['request_count'],d['tool_calls'],d['result_blocks'],d['source_count'])==(1,1,2,1)


def test_official_multiple_searches_keep_sources_usage_and_diagnostic(monkeypatch):
    seen=network(monkeypatch,response(('one','two')))
    job=store.create_job('synthetic',{'stage':'search'})
    rows,meta=asyncio.run(search_tools.native(dict(service(),_job_id=job['id']),'q'))
    assert len(seen)==1 and len(rows)==2 and meta['calls']==2
    d=meta['search_diagnostic']
    assert d['limit_status']=='provider_managed' and d['requested_limit']==1 and d['warnings']
    assert store.job(job['id'])['search_diagnostic']==d
    assert d['usage']['input_tokens']==100 and 'fixture-secret' not in json.dumps(d)


def test_other_service_still_stops_but_keeps_known_usage(monkeypatch):
    network(monkeypatch,response(('one','two')))
    with pytest.raises(ServiceFailure) as caught:
        asyncio.run(search_tools.native(service('https://relay.example'),'q'))
    exc=caught.value
    assert exc.details['category']=='search_limit_exceeded'
    assert exc.details['search_diagnostic']['tool_calls']==2
    assert exc.usage['input_tokens']==100 and exc.usage['estimated_cost']>0
    assert '中转站' not in str(exc) and '已停止使用该渠道' not in str(exc)


def test_missing_sources_preserves_diagnostic_before_validation(monkeypatch):
    network(monkeypatch,response(sources=False))
    job=store.create_job('synthetic',{'stage':'search'})
    with pytest.raises(SearchEvidenceMissing) as caught:
        asyncio.run(search_tools.native(dict(service(),_job_id=job['id']),'q'))
    assert store.job(job['id'])['search_diagnostic']['source_count']==0
    assert caught.value.usage['input_tokens']==100


def test_http_error_stops_without_retry_and_records_response(monkeypatch):
    seen=network(monkeypatch,{'error':{'type':'server_error'}},503)
    job=store.create_job('synthetic',{'stage':'search'})
    with pytest.raises(ServiceFailure):
        asyncio.run(search_tools.native(dict(service(),_job_id=job['id']),'q'))
    d=store.job(job['id'])['search_diagnostic']
    assert len(seen)==1 and d['http_status']==503 and d['response_received']
    assert d['tool_calls'] is None


def test_only_search_fingerprints_change():
    s=service()
    for kind in ('text','tools','image','search'):
        old=hashlib.sha256(json.dumps(['2.3.2',kind,s['base_url'],s['protocol'],s['model'],s['secret'],
            providers.test_parameters(s,kind),s['max_tokens'],s['temperature']],sort_keys=True).encode()).hexdigest()
        assert (providers.fingerprint(s,kind)==old)==(kind!='search')


def test_capability_accepts_internal_searches_without_changing_routes(client,monkeypatch):
    from backend.models import Settings
    cfg=providers.settings();cfg['services'][0].update(base_url='https://api.deepseek.com/anthropic',protocol='anthropic')
    providers.save_settings(Settings.model_validate(cfg));before=providers.settings()
    seen=network(monkeypatch,response(('one','two')))
    r=client.post('/api/services/s/capability-tests',headers=H,json={'model':'deepseek-flash','kind':'search','protocol':'anthropic'})
    assert r.status_code==200,r.text
    value=r.json()
    assert value['status']=='tested' and value['search_diagnostic']['tool_calls']==2 and value['test_version']=='2.3.3'
    assert len(seen)==1 and len(value['sources'])==2
    after=providers.settings()
    assert before['routes']==after['routes'] and before['search']==after['search'] and before['services']==after['services']


def test_responses_duplicate_ids_do_not_exceed_limit(monkeypatch):
    block=dict(id='search-one',type='web_search_call',status='completed',action={'sources':[{'url':'https://example.org'}]})
    network(monkeypatch,dict(output=[block,block],usage={'input_tokens':10,'output_tokens':2}))
    rows,meta=asyncio.run(search_tools.native(dict(service('https://relay.example'),protocol='responses'),'q'))
    assert len(rows)==1 and meta['calls']==1 and meta['search_diagnostic']['result_blocks']==2


def test_unpaired_or_non_web_sources_never_pass(monkeypatch):
    payload=response()
    payload['content'][1]['tool_use_id']='unrelated'
    network(monkeypatch,payload)
    with pytest.raises(SearchEvidenceMissing):asyncio.run(search_tools.native(service(),'q'))
    payload['content'][1].update(tool_use_id='one',content=[{'type':'web_search_result','url':'file:///private'}])
    with pytest.raises(SearchEvidenceMissing):asyncio.run(search_tools.native(service(),'q'))


def test_malformed_response_keeps_known_usage_and_http_status(monkeypatch):
    network(monkeypatch,dict(content=None,usage={'input_tokens':42,'output_tokens':9}))
    with pytest.raises(ServiceFailure) as caught:asyncio.run(search_tools.native(service(),'q'))
    exc=caught.value
    assert exc.details['category']=='malformed_response' and exc.details['http_status']==200
    assert exc.usage['input_tokens']==42


def test_cancel_is_not_retried(monkeypatch):
    real=httpx.AsyncClient;seen=[]
    def handler(request):seen.append(True);raise asyncio.CancelledError()
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(asyncio.CancelledError):asyncio.run(search_tools.native(service(),'q'))
    assert len(seen)==1


def test_streamed_duplicate_blocks_keep_counts_and_usage(monkeypatch):
    real=httpx.AsyncClient;payload=response(repeats=2)
    events=[dict(type='message_start',message={'usage':{'input_tokens':100}})]
    events.extend(dict(type='content_block_start',content_block=b) for b in payload['content'])
    events.extend([dict(type='message_delta',usage={'output_tokens':20}),dict(type='message_stop')])
    content=''.join('data: '+json.dumps(e)+'\n\n' for e in events)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,text=content,headers={'content-type':'text/event-stream'})),**kw))
    rows,meta=asyncio.run(search_tools.native(service(),'q'))
    assert meta['calls']==1 and meta['search_diagnostic']['result_blocks']==2
    assert meta['usage']=={'input_tokens':100,'output_tokens':20}


def test_task_uses_one_request_for_multiple_internal_searches(monkeypatch):
    from backend.execution_budget import BudgetExceeded
    from tests.test_native_runtime import session,article
    s=session(article());s.search_config.update(enabled=True,allow_fallback=False)
    s.limits['max_requests']=1
    monkeypatch.setattr(providers,'effective_service',lambda *_:service())
    seen=network(monkeypatch,response(('one','two')))
    rows=asyncio.run(s.search('synthetic'))
    job=store.job(s.job_id)
    assert len(seen)==1 and len(rows)==2 and job['execution_usage']['requests']==1
    assert job['search_diagnostic']['tool_calls']==2
    with pytest.raises(BudgetExceeded):asyncio.run(s.search('second'))
    assert len(seen)==1


def test_missing_prices_never_become_zero_cost(monkeypatch):
    network(monkeypatch,response())
    rows,meta=asyncio.run(search_tools.native(dict(service(),output_price=None),'q'))
    assert rows and meta['search_diagnostic']['usage']['estimated_cost'] is None


def test_research_keeps_diagnostic_and_charges_one_request(client,monkeypatch):
    from backend import research
    a=store.create_article({'topic':'synthetic'});j=store.create_job(a['id'],{'stage':'research'})
    w=research.Research(a,j['id'],'sources');w.search_model=service()
    network(monkeypatch,response(('one','two')))
    rows=asyncio.run(w.channel('native','synthetic'))
    job=store.job(j['id'])
    assert len(rows)==2 and job['execution_usage']['requests']==1 and job['search_diagnostic']['tool_calls']==2
