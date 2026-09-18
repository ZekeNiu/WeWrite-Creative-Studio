import asyncio
import pytest
from backend import store,providers,research,search_tools,academic
from backend.models import Settings,SearchConfig
from tests.test_research import client,network


def worker(preference,fallback=True,column='AI'):
    a=store.create_article({'column':column});j=store.create_job(a['id'],{'stage':'research'})
    w=research.Research(a,j['id'],'sources');w.target=1
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


@pytest.mark.parametrize('preference,expected',[('auto','native'),('native','native'),('tavily','tavily'),('browser','google')])
def test_preferred_way_runs_first(client,network,routes,preference,expected):
    w=worker(preference);asyncio.run(w.discover(['query']))
    assert (routes+network)==[expected]
    strategy=store.job(w.job_id)['research']['strategy']
    assert strategy['attempted']==[expected] and strategy['used']==[expected]
    assert strategy['preference']==preference


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
    w=worker('browser',False);asyncio.run(w.discover(['query']))
    assert engines==['google','bing'] and not routes and not w.policy_issue


def test_auto_without_fallback_selects_available_family(client,network,routes,monkeypatch):
    async def fail(*args): routes.append('tavily');raise ValueError('额度不足')
    monkeypatch.setattr(providers,'search',fail)
    w=worker('auto',False);w.search_model=None
    asyncio.run(w.discover(['query']))
    assert routes==['tavily'] and not network


def test_academic_supplement_follows_explicit_primary(client,network,routes,monkeypatch):
    async def scholarly(q):routes.append('openalex');return []
    async def crossref(q):routes.append('crossref');return []
    async def pubmed(q):routes.append('pubmed');return []
    monkeypatch.setattr(academic,'openalex',scholarly);monkeypatch.setattr(academic,'crossref',crossref);monkeypatch.setattr(search_tools,'pubmed',pubmed)
    w=worker('native',False,'运动科学');w.cfg.update(academic_enabled=True,pubmed_enabled=True)
    asyncio.run(w.discover(['query']))
    assert routes==['native','openalex','crossref','pubmed']
    assert not network and not w.policy_issue


def test_native_budget_failure_never_spills_when_switch_off(client,network,routes):
    w=worker('native',False);w.cfg['budget']=0
    asyncio.run(w.discover(['query']))
    assert not routes and not network and '预算' in w.policy_issue


def test_cached_channels_are_identified_without_new_requests(client,network,routes):
    first=worker('native');asyncio.run(first.discover(['cached-query']))
    second=worker('native');asyncio.run(second.discover(['cached-query']))
    assert routes==['native']
    assert second.strategy()['used']==['native'] and second.strategy()['attempted']==[]


def test_preference_roundtrip_preserves_text_and_routes(client):
    before=providers.settings();cfg=Settings.model_validate(before);cfg.search.preference='browser';cfg.search.allow_fallback=False
    after=providers.save_settings(cfg)
    assert before['services']==after['services'] and before['routes']==after['routes']
    assert after['search']['preference']=='browser' and after['search']['allow_fallback'] is False
    assert SearchConfig().preference=='auto' and SearchConfig().allow_fallback
