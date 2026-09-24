import asyncio
import pytest
from backend import store,providers,research,search_tools,academic
from backend.models import Settings,SearchConfig
from tests.test_research import client,network


def worker(preference,fallback=True,column='AI'):
    a=store.create_article({'column':column});j=store.create_job(a['id'],{'stage':'research'})
    w=research.Research(a,j['id'],'sources');w.notes_key=None
    w.cfg.update(preference=preference,allow_fallback=fallback,tavily_enabled=True,key_set=True)
    store.capability(providers.fingerprint(w.search_model,'search'),{'status':'tested'})
    return w


@pytest.fixture
def routes(monkeypatch):
    calls=[]
    async def native(*args):
        calls.append('native');return [{'url':'https://example.org/native','title':'原始资料','content':'摘要','provider':'native'}],{'calls':1}
    async def tavily(*args):
        calls.append('tavily');return [{'url':'https://example.org/tavily','title':'原始资料','content':'摘要'}]
    monkeypatch.setattr(search_tools,'native',native);monkeypatch.setattr(providers,'search',tavily)
    return calls


@pytest.mark.parametrize('preference,expected',[('auto','native'),('native','native'),('tavily','native'),('browser','native')])
def test_preferred_way_runs_first(client,network,routes,preference,expected):
    w=worker(preference);asyncio.run(w.discover(['query']))
    assert (routes+network)==[expected]
    strategy=store.job(w.job_id)['research']['strategy']
    assert strategy['attempted']==[expected] and strategy['used']==[expected]
    assert strategy['preference']=='native'


@pytest.mark.parametrize('fallback',[False,True])
def test_failure_switch_respects_choice(client,network,routes,monkeypatch,fallback):
    async def fail(*args): routes.append('native');raise ValueError('本次服务不可用')
    monkeypatch.setattr(search_tools,'native',fail)
    w=worker('native',fallback);asyncio.run(w.discover(['query']))
    assert routes==(['native','tavily'] if fallback else ['native']) and not network
    assert bool(w.policy_issue)==(not fallback)


@pytest.mark.parametrize('fallback',[False,True])
def test_unconfigured_primary_is_reported(client,network,routes,fallback):
    w=worker('native',fallback);w.search_model=None
    asyncio.run(w.discover(['query']))
    assert routes==(['tavily'] if fallback else [])
    assert any('尚未配置联网模型' in x['message'] for x in w.log)
    assert bool(w.policy_issue)==(not fallback)


def test_browser_only_can_change_engine_not_way(client,network,routes,monkeypatch):
    from backend import browser_search
    original=browser_search.search;engines=[]
    async def fail_google(q,engine):
        engines.append(engine)
        if engine=='google': raise ValueError('需要验证')
        return await original(q,engine)
    monkeypatch.setattr(browser_search,'search',fail_google)
    w=worker('native',True);w.search_model=None;w.cfg['tavily_enabled']=False;asyncio.run(w.discover(['query']))
    assert engines==['google','bing'] and not routes and not w.policy_issue


def test_legacy_auto_without_fallback_does_not_switch(client,network,routes,monkeypatch):
    async def fail(*args): routes.append('tavily');raise ValueError('额度不足')
    monkeypatch.setattr(providers,'search',fail)
    w=worker('auto',False);w.search_model=None
    asyncio.run(w.discover(['query']))
    assert not routes and not network and w.policy_issue


def test_sufficient_native_skips_academic_supplement(client,network,routes,monkeypatch):
    async def scholarly(q):routes.append('openalex');return []
    async def crossref(q):routes.append('crossref');return []
    async def pubmed(q):routes.append('pubmed');return []
    monkeypatch.setattr(academic,'openalex',scholarly);monkeypatch.setattr(academic,'crossref',crossref);monkeypatch.setattr(search_tools,'pubmed',pubmed)
    w=worker('native',False,'运动科学');w.cfg.update(academic_enabled=True,pubmed_enabled=True)
    asyncio.run(w.discover(['query']))
    assert routes==['native']
    assert not network and not w.policy_issue


def test_legacy_budget_does_not_block_native_when_fallback_off(client,network,routes):
    w=worker('native',False);w.cfg['budget']=0
    asyncio.run(w.discover(['query']))
    assert routes==['native'] and not network and not w.policy_issue


def test_cached_channels_are_identified_without_new_requests(client,network,routes):
    first=worker('native');asyncio.run(first.discover(['cached-query']))
    second=worker('native');asyncio.run(second.discover(['cached-query']))
    assert routes==['native']
    assert second.strategy()['used']==['native'] and second.strategy()['attempted']==[]


def test_preference_roundtrip_preserves_text_and_routes(client):
    before=providers.settings();cfg=Settings.model_validate(before);cfg.search.preference='browser';cfg.search.allow_fallback=False
    after=providers.save_settings(cfg)
    assert before['services']==after['services'] and before['routes']==after['routes']
    assert after['search']['preference']=='native' and after['search']['allow_fallback'] is False
    assert SearchConfig().preference=='native' and SearchConfig().allow_fallback


def test_untested_native_is_attempted_and_records_real_capability(client,network,routes):
    w=worker('native');key=providers.fingerprint(w.search_model,'search')
    store.capability(key,{'status':'untested'})
    asyncio.run(w.discover(['query']))
    assert routes==['native'] and store.capability(key)['status']=='tested'


def test_evidence_gap_uses_backup_even_with_many_native_sources(client,network,routes,monkeypatch):
    from backend import materials
    async def read(url):
        body='研究只适用于给定条件。'+(('补充材料。'*60) if url.endswith('/tavily') else ('初始材料。'*60))
        return materials.source(url,body,url,'web')
    monkeypatch.setattr(materials,'from_url',read)
    original=research.structured
    async def structured(a,stage,instruction,schema,job_id,candidates=None,questions=()):
        value=await original(a,stage,instruction,schema,job_id,candidates,questions=questions)
        if schema.__name__=='ResearchNotes' and not any(s.get('url','').endswith('/tavily') for s in a['sources']):
            value['gaps']=['缺少另一项关键事实']
        return value
    monkeypatch.setattr(research,'structured',structured)
    w=worker('native');asyncio.run(w.discover(['query']))
    assert routes==['native','tavily'] and w.sufficient()


def test_existing_material_sufficient_skips_all_search(client,network,routes,monkeypatch):
    from backend import materials
    w=worker('native');w.a['sources']=[materials.source('资料','研究只适用于给定条件。'*30)]
    original=research.structured
    async def structured(a,stage,instruction,schema,job_id,candidates=None,questions=()):
        value=await original(a,stage,instruction,schema,job_id,candidates,questions=questions)
        if schema.__name__=='ResearchPlan': value['needed']=False
        return value
    monkeypatch.setattr(research,'structured',structured)
    assert asyncio.run(w.run()) is False
    assert not routes and not network


def test_migration_is_idempotent_and_drops_legacy_limits(client):
    before=providers.settings();raw=store.get_settings()
    raw['search'].update(preference='browser',browser_enabled=False,max_calls=12,max_pages=32,max_rounds=4)
    raw['search'].pop('page_render_enabled',None);store.set_settings(raw)
    providers.migrate_settings();first=store.get_settings();providers.migrate_settings()
    assert store.get_settings()==first
    assert first['services']==raw['services'] and first['routes']==before['routes']
    assert first['search']['preference']=='native' and not first['search']['page_render_enabled']
    assert not any(k in first['search'] for k in ('max_calls','max_pages','max_rounds'))


def test_page_render_independent_of_search_engines(client,network,monkeypatch):
    from backend import materials,browser_search
    async def fail(url): raise ValueError('需要动态渲染')
    seen=[]
    async def read(url): seen.append(url);return dict(title='原文',text='研究只适用于给定条件。'*30,url=url)
    monkeypatch.setattr(materials,'from_url',fail);monkeypatch.setattr(browser_search,'read',read)
    w=worker('native');w.cfg.update(browser_enabled=False,page_render_enabled=True)
    result=asyncio.run(w.read(dict(url='https://example.org/dynamic',title='动态页')))
    assert seen and result['status']=='retrieved'
    w=worker('native');w.cfg.update(browser_enabled=True,page_render_enabled=False)
    result=asyncio.run(w.read(dict(url='https://example.org/another',title='动态页')))
    assert len(seen)==1 and result['status']=='unreadable'


def test_evidence_assessment_includes_supplemental_question(client,network,monkeypatch):
    w=worker('native');seen=[];original=research.structured
    async def structured(a,stage,instruction,schema,job_id,candidates=None,questions=()):
        seen.append(instruction)
        return await original(a,stage,instruction,schema,job_id,candidates,questions=questions)
    monkeypatch.setattr(research,'structured',structured)
    asyncio.run(w.assess());count=len(seen)
    asyncio.run(w.assess());assert len(seen)==count
    w.requirements='补充运动禁忌';w.questions=['哪些人不适用？']
    asyncio.run(w.assess())
    assert len(seen)==count+1 and '补充运动禁忌' in seen[-1] and '哪些人不适用？' in seen[-1]


def test_material_or_brief_edit_marks_saved_research_stale(client):
    a=store.create_article({'topic':'原主题'})
    a=store.save_article(a['id'],a['revision'],lambda x:x.update(research={'stage':'sources','stale':False,'summary':'历史结论'}),'fixture')
    a=store.save_article(a['id'],a['revision'],lambda x:x['brief'].update(topic='新主题'),'edit')
    assert a['research']['stale'] and a['research']['summary']=='历史结论'
