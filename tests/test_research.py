import asyncio
import io
import json
import time
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import app
from backend import store,providers,research,materials,search_tools,browser_search
from backend.models import Settings,JobRequest

H={'X-Studio-Request':'1'}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    with TestClient(app) as c:
        providers.save_settings(Settings.model_validate({'services':[{'id':'s','key':'fixture-secret','name':'Fixture','model':'text','protocol':'responses'}],
            'default_service':'s','routes':{'image':{'service_id':'s','model':'image'},'sources':{'service_id':'s','model':'analysis'}},
            'search':{'native_service_id':'s','native_model':'search','pubmed_enabled':False,'academic_enabled':False,'max_rounds':1}}))
        yield c


def article(client,column='AI'):
    return client.post('/api/articles',headers=H,json={'topic':'需要核对的主题','column':column}).json()


def wait(client,j):
    for _ in range(300):
        value=client.get('/api/jobs/'+j['id']).json()
        if value['status'] not in ('queued','running'): return value
        time.sleep(.01)
    pytest.fail('research job did not finish')


@pytest.fixture
def network(monkeypatch):
    called=[]
    async def allowed(url): return not ('127.0.0.1' in url)
    async def search(query,engine):
        called.append(engine)
        return [{'url':'https://example.org/research','title':'原始资料','content':'摘要线索'}]
    async def read(url):return materials.source('原始资料','研究只适用于给定条件。'*30,url,'web')
    async def model(s,system,prompt,emit=None):
        value=json.loads(prompt);kind=value['schema']['title'];ctx=value['context']
        if kind=='ResearchPlan': result={'needed':True,'queries':['exercise evidence'],'questions':['适用范围']}
        elif kind=='SearchSelection':result={'urls':[x['url'] for x in value['candidates']]}
        else:
            src=ctx['sources']
            result={'summary':'已核对适用条件','evidence':[{'source_id':src[0]['id'],'quote':'研究只适用于给定条件。','claim':'只能在研究范围内解释','boundary':'不能扩大因果'}] if src else [],
                    'gaps':[] if src else ['没有可用依据'],'conflicts':[],'followup_queries':[]}
        return json.dumps(result,ensure_ascii=False),{'model':s['model'],'service':s['name'],'estimated_cost':None,'status':'completed'}
    from backend import public_network
    monkeypatch.setattr(public_network,'public_url',allowed)
    monkeypatch.setattr(browser_search,'public_url',allowed)
    monkeypatch.setattr(browser_search,'search',search)
    monkeypatch.setattr(materials,'from_url',read)
    async def unavailable_native(s,*args):
        if s['protocol']=='gemini': return await search_tools.gemini(s,*args)
        raise ValueError('fixture native unavailable')
    monkeypatch.setattr(search_tools,'native',unavailable_native)
    monkeypatch.setattr(providers,'generate',model)
    return called


@pytest.mark.parametrize('column',['运动科学','运动健康','AI','建筑历史'])
def test_no_tavily_automatic_research_and_cache(client,network,column):
    a=article(client,column)
    j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'stage':'research','revision':a['revision'],'chain':False}).json()
    done=wait(client,j);assert done['status']=='completed',done
    a=client.get('/api/articles/'+a['id']).json()
    assert a['research']['summary'] and a['sources'][0]['evidence_spans'][0]['verification']=='quote_matched'
    assert a['sources'][0]['status']=='retrieved' and network==['google']
    assert providers.service_for('research')['model']=='analysis'
    j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'stage':'research','revision':a['revision'],'chain':False}).json()
    assert wait(client,j)['status']=='completed' and network==['google']


@pytest.mark.parametrize('protocol',['responses','anthropic'])
def test_native_requires_real_tools(monkeypatch,protocol):
    real=httpx.AsyncClient
    fake={'output':[{'type':'message','content':[{'type':'output_text','text':'我已联网搜索'}]}]} if protocol=='responses' else {'content':[{'type':'text','text':'我搜过了'}]}
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=fake)),**kw))
    with pytest.raises(ValueError,match='真实搜索工具'):
        asyncio.run(search_tools.native({'protocol':protocol,'base_url':'https://relay.example','secret':'test','model':'m'},'query'))


@pytest.mark.parametrize('protocol',['responses','anthropic'])
def test_native_accepts_only_tool_sources(monkeypatch,protocol):
    real=httpx.AsyncClient
    data={'output':[{'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://example.org','title':'出处'}]}}]} if protocol=='responses' else {
        'content':[{'type':'server_tool_use','id':'tool1','name':'web_search'}, {'type':'web_search_tool_result','tool_use_id':'tool1','content':[{'type':'web_search_result','url':'https://example.org','title':'出处'}]}]}
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=data)),**kw))
    rows,meta=asyncio.run(search_tools.native({'protocol':protocol,'base_url':'https://relay.example','secret':'test','model':'m'},'q'))
    assert rows[0]['url']=='https://example.org' and meta['calls']==1


def test_failed_native_falls_back_without_repeating(client,network,monkeypatch):
    calls=[];s=providers.effective_service('search');store.capability(providers.fingerprint(s,'search'),{'status':'tested'})
    async def fail(*args):calls.append(1);raise ValueError('搜索超时')
    monkeypatch.setattr(search_tools,'native',fail)
    a=article(client);j=store.create_job(a['id'],{'stage':'research'})
    async def execute():
        worker=research.Research(a,j['id'],'sources')
        await worker.discover(['first','second'])
        return worker
    w=asyncio.run(execute())
    assert len(calls)==1 and 'google' in network and w.added
    assert any(u['stage']=='search' and u['status']=='unknown' for u in store.usage(a['id']))


def test_legacy_budget_allows_unknown_price_native(client,network,monkeypatch):
    c=providers.settings();c['search']['budget']=0;providers.save_settings(Settings.model_validate(c))
    s=providers.effective_service('search');store.capability(providers.fingerprint(s,'search'),{'status':'tested'})
    calls=[]
    async def native(*args):
        calls.append('native')
        return [{'url':'https://example.org/research','title':'原始资料','content':'摘要线索'}],{'calls':1}
    monkeypatch.setattr(search_tools,'native',native)
    a=article(client);j=store.create_job(a['id'],{'stage':'research'});w=research.Research(a,j['id'],'sources')
    asyncio.run(w.discover(['q']))
    assert calls==['native'] and w.added and not network


def test_excluded_source_never_reintroduced(client,network):
    a=article(client);s=materials.source('排除来源','研究只适用于给定条件。'*30,'https://example.org/research','web');s['selected']=False
    a=store.save_article(a['id'],a['revision'],lambda v:v['sources'].append(s),'fixture')
    j=store.create_job(a['id'],{'stage':'research'});w=research.Research(a,j['id'],'sources')
    asyncio.run(w.discover(['q']))
    assert not w.added and not w.pages


def test_conflict_preserves_human_edit_and_pending_material(client,network,monkeypatch):
    orig=materials.from_url
    async def slow(url):await asyncio.sleep(.15);return await orig(url)
    monkeypatch.setattr(materials,'from_url',slow)
    a=article(client);j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'stage':'research','revision':a['revision']}).json()
    edited=client.patch('/api/articles/'+a['id'],headers=H,json={'revision':a['revision'],'stage':'write','changes':{'content':'新人工稿'}})
    assert edited.status_code==200
    done=wait(client,j);assert done['status']=='conflict'
    assert client.get('/api/articles/'+a['id']).json()['content']=='新人工稿'
    assert done['research']['sources']


def test_image_test_uses_node_override_without_price(client,monkeypatch):
    calls=[];blob=io.BytesIO();Image.new('RGB',(20,20)).save(blob,'PNG')
    async def image(s,*args):calls.append(s['model']);return blob.getvalue()
    monkeypatch.setattr(providers,'image_generate',image)
    r=client.post('/api/services/s/test-image',headers=H)
    assert r.status_code==200 and calls==['image']
    assert client.get(r.json()['image_url']).status_code==200
    cfg=client.get('/api/settings').json();assert cfg['route_capabilities']['image']['status']=='tested'
    cfg['routes']['image']['model']='different-image'
    cfg=client.put('/api/settings',headers=H,json=cfg).json()
    assert cfg['route_capabilities']['image']['status']=='untested'


def test_limits_and_cancel_preserve_original(client,network,monkeypatch):
    c=providers.settings();c['search'].update(max_calls=1,max_pages=1);providers.save_settings(Settings.model_validate(c))
    a=article(client);j=store.create_job(a['id'],{'stage':'research'});w=research.Research(a,j['id'],'sources')
    w.search_model=None  # Exercise the free channel's call/page caps.
    asyncio.run(w.discover(['q1','q2','q3']));assert w.calls==1 and w.pages==1
    store.update_job(j['id'],status='completed')
    async def slow(*args,**kwargs):await asyncio.sleep(5)
    monkeypatch.setattr(providers,'generate',slow)
    j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'stage':'research','revision':a['revision']}).json()
    client.post('/api/jobs/'+j['id']+'/cancel',headers=H)
    assert wait(client,j)['status']=='cancelled'
    assert client.get('/api/articles/'+a['id']).json()['revision']==a['revision']


def test_spans_cannot_invent_quote_or_pdf_page():
    src=materials.source('论文','证据片段。',pages=[{'page':3,'text':'证据片段。'}])
    notes={'evidence':[{'source_id':src['id'],'quote':'证据片段。','claim':'研究发现'},{'source_id':src['id'],'quote':'编造数字','claim':'夸张结果'}],'gaps':[]}
    out=research.validate_spans(notes,[src]);assert len(out['evidence'])==1 and out['evidence'][0]['page']==3 and out['gaps']


def test_pubmed_parses_abstract_as_abstract(monkeypatch):
    real=httpx.AsyncClient
    def handler(req):
        if 'esearch' in str(req.url):return httpx.Response(200,json={'esearchresult':{'idlist':['123']}})
        return httpx.Response(200,text='<PubmedArticleSet><PubmedArticle><PMID>123</PMID><ArticleTitle>Trial</ArticleTitle><Abstract><AbstractText>Only an abstract.</AbstractText></Abstract><ArticleId IdType="doi">10.1234/test</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId></PubmedArticle></PubmedArticleSet>')
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    rows=asyncio.run(search_tools.pubmed('exercise'))
    assert rows[1]['status']=='abstract_only' and rows[1]['doi']=='10.1234/test'
    assert rows[0]['url']=='https://pmc.ncbi.nlm.nih.gov/articles/PMC123/' and rows[0]['provider']=='pubmed_fulltext'
    assert rows[0]['status']=='excerpt_only'  # Fulltext is verified only after reading.


def test_missing_core_evidence_pauses_without_changing_draft(client,network,monkeypatch):
    original=providers.generate
    async def conflicting(s,system,prompt,emit=None):
        text,usage=await original(s,system,prompt,emit)
        if json.loads(prompt)['schema']['title']=='ResearchNotes':
            value=json.loads(text);value['gaps']=['核心人群无法确定，无法回答任务'];text=json.dumps(value)
        return text,usage
    monkeypatch.setattr(providers,'generate',conflicting)
    a=article(client);a=store.save_article(a['id'],a['revision'],lambda v:v.update(content='保留的正文'),'fixture')
    j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'stage':'review','revision':a['revision']}).json()
    assert wait(client,j)['status']=='needs_input'
    a=client.get('/api/articles/'+a['id']).json()
    assert a['content']=='保留的正文' and a['stages']['review']=='needs_input' and a['research']['gaps']


def test_restart_marks_search_interrupted_without_replay(client):
    a=article(client);j=store.create_job(a['id'],{'stage':'research','revision':a['revision']})
    store.update_job(j['id'],status='running',research={'calls':2,'sources':[]})
    store.init()
    assert store.job(j['id'])['status']=='interrupted' and store.job(j['id'])['research']['calls']==2


def test_private_urls_and_fake_proxy_dns(monkeypatch):
    from backend import public_network as net
    net.CACHE.clear()
    assert not asyncio.run(net.public_url('http://127.0.0.1'))
    assert not asyncio.run(net.public_url('http://[::1]/'))
    assert not asyncio.run(net.public_url('https://user:password@example.org'))
    assert not asyncio.run(net.public_url('file:///C:/Windows'))
    assert not asyncio.run(net.public_url('http://198.18.0.1'))
    monkeypatch.setattr(net.socket,'getaddrinfo',lambda *args:[(2,1,6,'',('198.18.0.4',443))])
    monkeypatch.setattr(net.urllib.request,'getproxies',lambda:{'https':'http://127.0.0.1:7897'})
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'Status':0,'Answer':[{'type':1,'data':'93.184.216.34'}]})),**kw))
    assert asyncio.run(net.public_url('https://public.example.org'))
    net.CACHE.clear()
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'Status':0,'Answer':[{'type':1,'data':'10.0.0.1'}]})),**kw))
    assert not asyncio.run(net.public_url('https://private.example.org'))


def test_native_stream_cutoff_is_not_success(monkeypatch):
    real=httpx.AsyncClient
    events=[{'type':'content_block_start','content_block':{'type':'server_tool_use','name':'web_search','id':'s1'}},
            {'type':'content_block_start','content_block':{'type':'web_search_tool_result','tool_use_id':'s1','content':[{'type':'web_search_result','url':'https://example.org'}]}}]
    body=''.join('data: '+json.dumps(x)+'\n\n' for x in events)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/event-stream'},text=body)),**kw))
    with pytest.raises(ValueError,match='中断'):
        asyncio.run(search_tools.native({'protocol':'anthropic','secret':'test','base_url':'https://relay.example','model':'m'},'q'))


def test_irrelevant_search_results_not_adopted(client,network,monkeypatch):
    original=providers.generate
    async def reject(s,system,prompt,emit=None):
        if json.loads(prompt)['schema']['title']=='SearchSelection': return '{"urls":[],"reason":"与主题无关"}',{'model':s['model'],'status':'completed','estimated_cost':None}
        return await original(s,system,prompt,emit)
    monkeypatch.setattr(providers,'generate',reject)
    a=article(client);j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'stage':'research','revision':a['revision']}).json()
    assert wait(client,j)['status']=='needs_input'
    a=client.get('/api/articles/'+a['id']).json()
    assert a['sources']==[] and a['research']['pending'] and a['research']['gaps']


def test_workbench_check_without_native_or_tavily(client,network):
    cfg=providers.settings();cfg['services'][0]['protocol']='chat'
    providers.save_settings(Settings.model_validate(cfg))
    before=providers.settings()
    native=client.post('/api/search/native/test',headers=H).json()
    assert native['status']=='unused'
    job=client.post('/api/search/check',headers=H,json={'column':'AI','without_tavily':True}).json()
    wait(client,job)
    result=client.get('/api/search/check/'+job['id']).json()
    assert result['passed'] and all(x=='passed' for x in result['steps'].values())
    assert result['evidence'][0]['quote']=='研究只适用于给定条件。'
    assert client.get('/api/articles').json()==[]
    assert providers.settings()==before
    cfg['routes']['sources']['model']='another'
    providers.save_settings(Settings.model_validate(cfg))
    assert client.get('/api/search/check/latest').json()['stale']


def test_check_snippets_cannot_pass(client,network,monkeypatch):
    async def unavailable(*args):raise ValueError('网页打不开')
    monkeypatch.setattr(materials,'from_url',unavailable)
    monkeypatch.setattr(browser_search,'read',unavailable)
    j=client.post('/api/search/check',headers=H,json={'column':'AI'}).json();wait(client,j)
    r=client.get('/api/search/check/latest').json()
    assert not r['passed'] and r['steps']['reading']=='failed'


def test_tavily_first_and_quota_fallback(client,network,monkeypatch):
    cfg=providers.settings();cfg['search'].update(key='test-tavily',tavily_enabled=True)
    providers.save_settings(Settings.model_validate(cfg));order=[]
    async def quota(*args):order.append('tavily');raise ValueError('额度不足')
    previous=browser_search.search
    async def browser(*args):order.append(args[1]);return await previous(*args)
    monkeypatch.setattr(providers,'search',quota);monkeypatch.setattr(browser_search,'search',browser)
    j=client.post('/api/search/check',headers=H,json={'column':'AI'}).json();wait(client,j)
    r=client.get('/api/search/check/latest').json()
    assert r['passed'] and order==['tavily','google']
    assert any(x.get('reason')=='额度不足' for x in r['research']['log'])


def test_check_deduplicates_start_and_can_stop(client,network,monkeypatch):
    async def slow(*args,**kwargs):await asyncio.sleep(5)
    monkeypatch.setattr(providers,'generate',slow)
    j=client.post('/api/search/check',headers=H,json={'column':'AI'}).json()
    again=client.post('/api/search/check',headers=H,json={'column':'AI'}).json()
    assert j['id']==again['id']
    client.post('/api/jobs/'+j['id']+'/cancel',headers=H)
    assert wait(client,j)['status']=='cancelled'


def test_article_extraction_skips_teaser_card_and_challenges(monkeypatch):
    async def fetch(url):
        return ('<html><title>Research</title><article>Journal teaser</article><main>'+('Actual paper findings. '*40)+'</main></html>').encode(),url
    monkeypatch.setattr(materials,'fetch_bytes',fetch)
    src=asyncio.run(materials.from_url('https://example.org/paper'))
    assert 'Actual paper findings.' in src['text'] and 'Journal teaser' not in src['text']
    assert materials.blocked_page('Client Challenge','Please enable JavaScript')
    src=asyncio.run(materials.from_url('https://pubmed.ncbi.nlm.nih.gov/123/'))
    assert src['status']=='abstract_only'


def test_third_browser_fallback_after_captcha(client,network,monkeypatch):
    previous=browser_search.search;called=[]
    async def limited(query,engine):
        called.append(engine)
        if engine in ('google','bing','baidu'):raise ValueError('搜索页面需要验证')
        return await previous(query,engine)
    monkeypatch.setattr(browser_search,'search',limited)
    j=client.post('/api/search/check',headers=H,json={'column':'AI','without_tavily':True}).json();wait(client,j)
    result=client.get('/api/search/check/latest').json()
    assert result['passed'] and called==['google','bing','baidu','duckduckgo']
    assert len(result['research']['blocked_urls'])==3


def test_ai_selection_failure_is_reported_as_ai(client,network,monkeypatch):
    async def failed(*args,**kwargs):raise ValueError('模型额度不足')
    monkeypatch.setattr(providers,'generate',failed)
    j=client.post('/api/search/check',headers=H,json={'column':'AI'}).json();wait(client,j)
    r=client.get('/api/search/check/latest').json()
    assert not r['passed'] and 'AI 筛选未完成' in r['error']


def test_free_fallback_url_unwrap():
    assert browser_search.unwrap('//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpaper')=='https://example.org/paper'


def test_research_preserves_partial_stream_and_user_output_limit(client,network,monkeypatch):
    async def interrupted(s,system,prompt,emit=None):
        assert s['max_tokens']==providers.service_for('research')['max_tokens']
        await emit('{"urls": [')
        raise ValueError('连接中断')
    monkeypatch.setattr(providers,'generate',interrupted)
    j=client.post('/api/search/check',headers=H,json={'column':'AI'}).json()
    assert wait(client,j)['partial']=='{"urls": ['
